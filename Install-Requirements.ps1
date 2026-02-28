# Activate the venv
.\.venv\Scripts\Activate.ps1

# Re-install everything from requirements.txt (including python-multipart)
#py -m pip install -r .\requirements.txt
# If python is weird on your PATH inside the venv, you can be explicit:
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt