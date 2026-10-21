package com.usmanzade.gmx;

final class Targets {
    private Targets() {}

    static final Target LAUNCH = new Target("launch", null, null, false, new String[] {"android.os.Bundle"}, "void", null,
            new String[][] {{"org.telegram.ui.LaunchActivity", "onCreate"}});
    static final Target PREMIUM = new Target("premium", "telegram", Boolean.TRUE, false, new String[] {}, "boolean", "org.telegram.tgnet.TLRPC$User",
            new String[][] {{"org.telegram.messenger.v40", "w"}});
    static final Target EXPIRE = new Target("expire", "telegraph", Boolean.FALSE, true, new String[] {"long"}, null, null,
            new String[][] {{"org.telegram.tgnet.ConnectionsManager", "native_expireFile"}});
    static final Target DAYS = new Target("days", "telegraph", Integer.valueOf(999), true, new String[] {"long"}, null, null,
            new String[][] {{"org.telegram.tgnet.ConnectionsManager", "native_daysFile"}});
    static final Target LICENSE = new Target("license", "telegraph", Boolean.TRUE, true, new String[] {"long"}, null, null,
            new String[][] {{"org.telegram.tgnet.ConnectionsManager", "native_checkLicense"}});
    static final Target REMOVE = new Target("remove", "telegraph", Boolean.TRUE, true, new String[] {"int", "boolean"}, null, null,
            new String[][] {{"org.telegram.tgnet.ConnectionsManager", "native_removeInstance"}});

    static final Target[] CONSTANTS = {PREMIUM, EXPIRE, DAYS, LICENSE, REMOVE};

    static final Target ANCHOR = LAUNCH;
}
