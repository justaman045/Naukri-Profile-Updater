
import re


#=====================================================================URLs=========================================================


LOGIN_URL = "https://www.naukri.com/central-login-services/v1/login"
OTP_VERIFY_URL = "https://www.naukri.com/central-login-services/v0/otp-login"
OTP_SEND_URL = "https://www.naukri.com/central-login-services/v1/otp"
PROFILE_URL = "https://www.naukri.com/mnjuser/profile"
FILE_VALIDATION_URL = "https://filevalidation.naukri.com/file"
DASHBOARD_URL = "https://www.naukri.com/cloudgateway-mynaukri/resman-aggregator-services/v0/users/self/dashboard"
PROFILE_UPDATE_URL= "https://www.naukri.com/cloudgateway-mynaukri/resman-aggregator-services/v1/users/self/fullprofiles"
PROFILE_FETCH_URL = "https://www.naukri.com/cloudgateway-mynaukri/resman-aggregator-services/v1/users/self/fullprofiles"
FULL_PROFILE_URL = "https://www.naukri.com/cloudgateway-mynaukri/resman-aggregator-services/v2/users/self"
RESUME_DOWNLOAD_URL_TEMPLATE = "https://www.naukri.com/cloudgateway-mynaukri/resman-aggregator-services/v1/users/self/profiles/{profile_id}/resume"
RESUME_UPDATE_URL_TEMPLATE = "https://www.naukri.com/cloudgateway-mynaukri/resman-aggregator-services/v0/users/self/profiles/{profile_id}/advResume"
JOB_SEARCH_URL = "https://www.naukri.com/jobapi/v3/search"
RECOMMENDED_JOBS_URL = "https://www.naukri.com/jobapi/v2/search/recom-jobs"
APPLY_JOB_URL = "https://www.naukri.com/cloudgateway-workflow/workflow-services/apply-workflow/v1/apply"
HISTORY_URL = "https://www.naukri.com/cloudgateway-apply/whtma-services/v0/applyapi/v5/history"


 #===================================================================================================================================

#=======================================RSA public key===============================

PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MFwwDQYJKoZIhvcNAQEBBQADSwAwSAJBALrlQ+djR0RjJwBF1xuisHmdFv334MIm
K6LgzJhmLhN7B5yuEyaKoasgXQk3+OQglsOaBxEJ0j5PcTL3nbOvt80CAwEAAQ==
-----END PUBLIC KEY-----"""
#==================================================================================

FORM_KEY_PATTERNS = [
    re.compile(r'formKey\s*[:=]\s*["\']([A-Za-z0-9]{8,})["\']'),
    re.compile(r'"formKey"\s*:\s*"([A-Za-z0-9]{8,})"'),
]

# The profile-page resume uploader (bundle `mnj_v<NNN>.min.js`) declares its key
# as `c="attachCV",d="<key>"`. This is a DIFFERENT key from the chat uploader in
# `app_v<NNN>.min.js` (`this.formKey="<key>"`); using the wrong one makes the
# filevalidation upload return a fake/honeypot key that the advResume attach
# cannot resolve (404 "Received 404 from OCS Service"). Extract the attachCV one.
RESUME_FORM_KEY_PATTERNS = [
    re.compile(r'["\']attachCV["\']\s*,\s*[A-Za-z_$][\w$]*\s*=\s*["\']([A-Za-z0-9]{8,})["\']'),
]

APP_JS_PATTERN = re.compile(r'<script[^>]+src="([^"]*app_v\d+\.min\.js[^"]*)"')

# The app bundle carries a version map: `_c={app:"_v470",mnj:"_v323",...}`.
# The profile resume uploader's JS lives in `mnj_v<NNN>.min.js`; read NNN here
# so we can build the current bundle URL (the version rotates).
MNJ_VERSION_PATTERN = re.compile(r'mnj\s*:\s*["\']_?v(\d+)["\']')
