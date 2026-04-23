import sys
import os
import io
import zipfile

def analyze_zip(zip_bytes):
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for info in z.infolist():
            print(info.filename)

if __name__ == "__main__":
    print("hi")
