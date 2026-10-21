package com.usmanzade.gmx;

import android.util.Log;

import io.github.libxposed.api.XposedInterface;
import io.github.libxposed.api.XposedModule;
import io.github.libxposed.api.XposedModuleInterface;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

public final class GmxModule extends XposedModule {

    private static final String TAG = "GMX";
    private static final String PACKAGE = "ir.ilmili.telegraph";

    private volatile boolean mainProcess;
    private final AtomicBoolean nativesInstalled = new AtomicBoolean();
    private final Map<String, int[]> outcome = new LinkedHashMap<>();

    @Override
    public void onModuleLoaded(XposedModuleInterface.ModuleLoadedParam param) {
        mainProcess = PACKAGE.equals(param.getProcessName());
        if (!mainProcess) {
            detach();
        }
    }

    @Override
    public void onPackageReady(XposedModuleInterface.PackageReadyParam param) {
        if (!mainProcess || !param.isFirstPackage() || !PACKAGE.equals(param.getPackageName())) {
            return;
        }
        final ClassLoader cl = param.getClassLoader();

        for (Target t : Targets.CONSTANTS) {
            if (!t.nativeMethod) {
                replace(cl, t);
            }
        }

        boolean deferred = false;
        final Target anchor = Targets.ANCHOR;
        if (anchor != null) {
            try {
                hook(resolve(cl, anchor))
                        .setId("gmx." + anchor.id)
                        .setExceptionMode(XposedInterface.ExceptionMode.PROTECTIVE)
                        .intercept(chain -> {
                            installNatives(cl);
                            return chain.proceed();
                        });
                deferred = true;
            } catch (Throwable t) {
                log(Log.DEBUG, TAG, "anchor " + anchor.id + " unavailable, hooking native targets now: " + describe(t));
            }
        }
        if (!deferred) {
            installNatives(cl);
        }
    }

    private void installNatives(ClassLoader cl) {
        if (!nativesInstalled.compareAndSet(false, true)) return;
        for (Target t : Targets.CONSTANTS) {
            if (t.nativeMethod) {
                replace(cl, t);
            }
        }
        report();
    }

    private void report() {
        int applied = 0;
        int incomplete = 0;
        for (int[] counts : outcome.values()) {
            if (counts[1] > 0) incomplete++;
            if (counts[0] > 0) applied++;
        }
        if (incomplete == 0 && applied > 0) {
            log(Log.INFO, TAG, "all hooks are applied");
            return;
        }
        for (Map.Entry<String, int[]> e : outcome.entrySet()) {
            int[] counts = e.getValue();
            String what = e.getKey() + " premium is ";
            if (counts[1] == 0) {
                log(Log.INFO, TAG, what + "applied");
            } else if (counts[0] == 0) {
                log(Log.ERROR, TAG, what + "not applied");
            } else {
                log(Log.ERROR, TAG, what + "partially applied");
            }
        }
        if (applied == 0) {
            log(Log.WARN, TAG, "no hooks are applied, module is idle");
            try {
                detach();
            } catch (Throwable ignored) {
            }
        }
    }

    private void replace(ClassLoader cl, Target t) {
        try {
            Method method = resolve(cl, t);
            final Object result = coerce(method.getReturnType(), t.value);
            hook(method)
                    .setId("gmx." + t.id)
                    .setExceptionMode(XposedInterface.ExceptionMode.PROTECTIVE)
                    .intercept(chain -> result);
            count(t, true);
            log(Log.DEBUG, TAG, "hook " + t.id + ": " + method.getDeclaringClass().getName()
                    + "#" + method.getName());
        } catch (Throwable e) {
            count(t, false);
            log(Log.DEBUG, TAG, "hook " + t.id + " failed: " + describe(e));
        }
    }

    private void count(Target t, boolean ok) {
        int[] counts = outcome.get(t.group);
        if (counts == null) {
            counts = new int[2];
            outcome.put(t.group, counts);
        }
        counts[ok ? 0 : 1]++;
    }

    private static String describe(Throwable t) {
        return t instanceof NoSuchMethodException ? t.getMessage() : t.toString();
    }

    private static Method resolve(ClassLoader cl, Target t) throws NoSuchMethodException {
        StringBuilder why = new StringBuilder();
        for (String[] v : t.variants) {
            try {
                return resolve(cl, v[0], v[1], t);
            } catch (NoSuchMethodException e) {
                if (why.length() > 0) why.append("; ");
                why.append(e.getMessage());
            }
        }
        throw new NoSuchMethodException(why.toString());
    }

    private static Method resolve(ClassLoader cl, String className, String name, Target t)
            throws NoSuchMethodException {
        String where = className + "#" + name;
        Class<?> clazz;
        try {
            clazz = Class.forName(className, false, cl);
        } catch (Throwable e) {
            throw new NoSuchMethodException(where + ": class not found");
        }

        Method found = null;
        try {
            for (Method m : clazz.getDeclaredMethods()) {
                if (m.getName().equals(name)
                        && (!t.nativeMethod || Modifier.isNative(m.getModifiers()))
                        && (t.returnType == null || m.getReturnType().getName().equals(t.returnType))
                        && sameParams(m.getParameterTypes(), t.params)) {
                    found = m;
                    break;
                }
            }
            if (found != null && t.marker != null) {
                boolean present = false;
                for (Field f : clazz.getDeclaredFields()) {
                    if (f.getType().getName().equals(t.marker)) {
                        present = true;
                        break;
                    }
                }
                if (!present) {
                    throw new NoSuchMethodException(where + ": structural marker missing");
                }
            }
        } catch (NoSuchMethodException e) {
            throw e;
        } catch (Throwable e) {
            throw new NoSuchMethodException(where + ": cannot inspect class");
        }
        if (found == null) {
            throw new NoSuchMethodException(where + ": no method with this exact signature");
        }
        return found;
    }

    private static boolean sameParams(Class<?>[] actual, String[] expected) {
        if (actual.length != expected.length) return false;
        for (int i = 0; i < actual.length; i++) {
            if (!actual[i].getName().equals(expected[i])) return false;
        }
        return true;
    }

    private static Object coerce(Class<?> type, Object value) throws NoSuchMethodException {
        if (type == void.class) return null;
        boolean flag = value instanceof Boolean ? (Boolean) value : ((Number) value).intValue() != 0;
        int number = value instanceof Number ? ((Number) value).intValue() : (flag ? 1 : 0);
        if (type == boolean.class) return flag;
        if (type == int.class) return number;
        if (type == long.class) return (long) number;
        throw new NoSuchMethodException("unsupported return type " + type.getName());
    }
}
