import os

# The API tests don't need the Node accounts server (auth/), which has its own tests.
os.environ.setdefault("MHD_NO_ACCOUNTS", "1")
