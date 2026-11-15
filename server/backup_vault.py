"""Stream-encrypted backup IO. Authenticate the complete archive before releasing plaintext."""
import argparse
import os
import sys
from pathlib import Path
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes

AAD=b'WegoH backup v1'

def key():
    file=Path(os.environ['WEGOH_VISIT_KEY_FILE'])
    if file.stat().st_mode & 0o007:raise ValueError('Unsafe backup key permissions')
    raw=file.read_bytes()
    if len(raw)!=32:raise ValueError('Invalid backup key')
    return raw

def encrypt(source,target):
    nonce=os.urandom(12);encryptor=Cipher(algorithms.AES(key()),modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(AAD);target.write(b'WB01'+nonce)
    while chunk:=source.read(65536):target.write(encryptor.update(chunk))
    target.write(encryptor.finalize());target.write(encryptor.tag)

def decrypt(source,target=None):
    source.seek(0,2);size=source.tell()
    if size<32:raise ValueError('Truncated encrypted backup')
    source.seek(0);header=source.read(16)
    if header[:4]!=b'WB01':raise ValueError('Invalid backup format')
    source.seek(-16,2);tag=source.read(16)
    decryptor=Cipher(algorithms.AES(key()),modes.GCM(header[4:],tag)).decryptor()
    decryptor.authenticate_additional_data(AAD);source.seek(16);remaining=size-32
    while remaining:
        chunk=source.read(min(65536,remaining))
        if not chunk:raise ValueError('Truncated encrypted backup')
        plain=decryptor.update(chunk);remaining-=len(chunk)
        if target is not None:target.write(plain)
    last=decryptor.finalize()
    if target is not None:target.write(last)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['encrypt','verify','decrypt']);parser.add_argument('path')
    args=parser.parse_args()
    if args.mode=='encrypt':
        fd=os.open(args.path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as output:encrypt(sys.stdin.buffer,output)
    else:
        with open(args.path,'rb') as source:
            decrypt(source)  # First pass releases nothing unless authentication succeeds.
            if args.mode=='decrypt':decrypt(source,sys.stdout.buffer)
