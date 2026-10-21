package com.usmanzade.gmx;

final class Target {
    final String id;
    final String group;
    final Object value;
    final boolean nativeMethod;
    final String[] params;
    final String returnType;
    final String marker;
    final String[][] variants;

    Target(String id, String group, Object value, boolean nativeMethod, String[] params, String returnType,
           String marker, String[][] variants) {
        this.id = id;
        this.group = group;
        this.value = value;
        this.nativeMethod = nativeMethod;
        this.params = params;
        this.returnType = returnType;
        this.marker = marker;
        this.variants = variants;
    }
}
