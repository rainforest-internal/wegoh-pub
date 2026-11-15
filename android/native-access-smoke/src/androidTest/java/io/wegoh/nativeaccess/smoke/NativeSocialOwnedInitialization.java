package io.wegoh.nativeaccess.smoke;

import android.content.Context;
import io.wegoh.app.nativeauth.VehicleConnection;
import java.security.cert.X509Certificate;

// Test APK only: the exact existing internal JVM symbol from the real debug AAR.
// This is neither a public SDK initializer nor a source copy of the library.
final class NativeSocialOwnedInitialization {
    static VehicleConnection create(Context context, String profile, int port, X509Certificate ca, int eventsPort) {
        return VehicleConnection.Companion.synthetic$native_access_debug(context, profile, port, ca, eventsPort);
    }
}
