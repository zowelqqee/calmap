Apple root certificate for verifying App Store purchases.

Download it here on the server (it is public; Apple publishes it):

    curl -fsSL -o AppleRootCA-G3.cer https://www.apple.com/certificateauthority/AppleRootCA-G3.cer

Without a `*.cer` file App Store purchases are refused (503).
