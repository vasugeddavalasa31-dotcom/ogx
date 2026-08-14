/**
 * Validates environment configuration for the application
 * This is called during server initialization
 */
export function validateServerConfig() {
  if (process.env.NODE_ENV === "development") {
    console.log("🚀 Starting OGX UI Server...");

    // Check optional configurations
    const optionalConfigs = {
      OGX_BACKEND_URL: process.env.OGX_BACKEND_URL || "http://localhost:8321",
      OGX_UI_PORT: process.env.OGX_UI_PORT || "8322",
      OGX_UI_ADMIN_EMAILS: process.env.OGX_UI_ADMIN_EMAILS,
      OGX_UI_ADMIN_PASSWORD: process.env.OGX_UI_ADMIN_PASSWORD,
      OGX_UI_SESSION_SECRET: process.env.OGX_UI_SESSION_SECRET,
    };

    console.log("\n📋 Configuration:");
    console.log(`   - Backend URL: ${optionalConfigs.OGX_BACKEND_URL}`);
    console.log(`   - UI Port: ${optionalConfigs.OGX_UI_PORT}`);
    console.log(
      `   - Admin emails: ${optionalConfigs.OGX_UI_ADMIN_EMAILS || "(default list)"}`
    );
    console.log(
      `   - Admin password: ${optionalConfigs.OGX_UI_ADMIN_PASSWORD ? "(set)" : "(default)"}`
    );
    console.log(
      `   - Session secret: ${optionalConfigs.OGX_UI_SESSION_SECRET ? "(set)" : "(default — set OGX_UI_SESSION_SECRET in production)"}`
    );

    console.log("");
  }
}

// Call this function when the module is imported
validateServerConfig();
