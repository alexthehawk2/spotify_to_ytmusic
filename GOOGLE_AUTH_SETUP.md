# Setting Up Google OAuth Credentials

Google recently tightened their security. To use this migration tool, you must create your own "OAuth Client ID" in the Google Cloud Console. This ensures your migration is private and doesn't get blocked by Google's bot filters.

### Step 1: Create a Google Cloud Project
1.  Go to [Google Cloud Console](https://console.cloud.google.com/).
2.  Click the project dropdown in the top left and select **New Project**.
3.  Name it `Spotify Migrator` and click **Create**.

### Step 2: Enable the YouTube API
1.  In the top search bar, search for **YouTube Data API v3**.
2.  Click the result and click the blue **Enable** button.

### Step 3: Configure the Consent Screen
1.  Go to **APIs & Services > OAuth consent screen** in the left sidebar.
2.  Select **User Type: External** and click **Create**.
3.  Fill in the required fields:
    *   **App name:** `My Migrator`
    *   **User support email:** Your email address.
    *   **Developer contact info:** Your email address.
4.  Click **Save and Continue** until you reach the **Test Users** tab.
5.  **CRITICAL:** Click **+ ADD USERS** and enter your own email address. (If you don't do this, the login will fail with a "403 Access Blocked" error).
6.  Click **Save and Continue**.

### Step 4: Create Credentials
1.  Go to **APIs & Services > Credentials** in the left sidebar.
2.  Click **+ CREATE CREDENTIALS** at the top and select **OAuth client ID**.
3.  **Application Type:** Select **TVs and Limited Input devices**.
4.  **Name:** Give it any name (e.g., `Desktop Migrator`).
5.  Click **Create**.

### Step 5: Use in App
1.  Copy your **Client ID** and **Client Secret**.
2.  Paste them into the **Advanced Settings** section of the Spotify to YT Music web app.
3.  Start your migration!
