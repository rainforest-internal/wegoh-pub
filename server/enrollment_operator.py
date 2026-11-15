"""Read-only CA-ID discovery for the operator; never prints tokens, CSR or names."""
import argparse
import http.client
import json
import re
import ssl

from enrollment_crypto import CF_ID, ID, EnrollmentError, read_cf_token


def discover_ca(zone, token_file, fingerprint=None):
    if not ID.fullmatch(zone) or (fingerprint and not re.fullmatch(r'[a-f0-9]{64}',fingerprint)):
        raise EnrollmentError('INVALID_CONFIGURATION')
    token=read_cf_token(token_file)
    ca_ids=set(); matches=0; pages=None
    context=ssl.create_default_context(); context.minimum_version=context.maximum_version=ssl.TLSVersion.TLSv1_3
    for page in range(1,11):
        conn=None
        try:
            conn=http.client.HTTPSConnection('api.cloudflare.com',context=context,timeout=15)
            conn.request('GET',f'/client/v4/zones/{zone}/client_certificates?status=active&per_page=50&page={page}',
                headers={'Authorization':'Bearer '+token})
            response=conn.getresponse(); raw=response.read(1048577)
            if response.status!=200 or len(raw)>1048576:
                raise ValueError()
            result=json.loads(raw)
            if result.get('success') is not True or not isinstance(result.get('result'),list):
                raise ValueError()
            info=result.get('result_info',{})
            total=info.get('total_pages')
            if type(total) is not int or not 1<=total<=10 or (pages is not None and total!=pages):
                raise ValueError()
            pages=total
            for item in result['result']:
                if item.get('status')!='active':
                    raise ValueError()
                if fingerprint and item.get('fingerprint_sha256')!=fingerprint:
                    continue
                ca=item.get('certificate_authority',{}).get('id','')
                if not CF_ID.fullmatch(ca):
                    raise ValueError()
                ca_ids.add(ca); matches+=1
            if page==pages:
                break
        except Exception:
            raise EnrollmentError('ISSUER_METADATA_UNAVAILABLE') from None
        finally:
            if conn is not None: conn.close()
    if len(ca_ids)!=1 or (fingerprint and matches!=1):
        raise EnrollmentError('ISSUER_METADATA_AMBIGUOUS')
    return dict(issuerId=next(iter(ca_ids)),activeCertificatesMatched=matches)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zone',required=True)
    parser.add_argument('--token-file',required=True)
    parser.add_argument('--certificate-sha256')
    args=parser.parse_args()
    try:
        value=discover_ca(args.zone,args.token_file,args.certificate_sha256)
    except EnrollmentError as error:
        print(json.dumps(dict(error=str(error))))
        return 1
    print(json.dumps(value))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
