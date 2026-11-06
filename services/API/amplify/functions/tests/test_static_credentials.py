import importlib.util, json, os, unittest
from pathlib import Path
from unittest.mock import patch
path=Path(__file__).resolve().parents[1]/'shared/static_credentials.py'
spec=importlib.util.spec_from_file_location('static_credentials',path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class Secrets:
    def __init__(self):self.reads=[];self.writes=[]
    def get_secret_value(self,**kwargs):self.reads.append(kwargs);return {'SecretString':'dynamic'}
    def put_secret_value(self,**kwargs):self.writes.append(kwargs);return {'VersionId':'updated'}
class Parameters:
    def __init__(self,value='raw',error=None):self.value=value;self.error=error;self.reads=[]
    def get_parameter(self,**kwargs):
        self.reads.append(kwargs)
        if self.error:raise self.error
        return {'Parameter':{'Value':self.value}}
class CredentialTests(unittest.TestCase):
    def setUp(self):self.sm=Secrets();self.pm=Parameters();self.reader=module.StaticCredentialClient(self.sm,self.pm)
    def test_preserves_raw_json_and_multiline_pem(self):
        for value in ['{ "client_secret": "abc" }','-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n']:
            self.pm.value=value
            self.assertEqual(self.reader.get_secret_value(SecretId=module._LOCATIONS[0]['sourceArn'])['SecretString'],value)
        self.assertFalse(self.sm.reads)
    def test_old_and_new_identifiers_use_same_free_parameter(self):
        pairs=[r for r in module._LOCATIONS if r['sourceName'].endswith('google-production') and ':820323452649:' in r['sourceArn']]
        self.assertEqual(len(pairs),2)
        for r in pairs:self.reader.get_secret_value(SecretId=r['sourceArn'])
        self.assertEqual(self.pm.reads[0],self.pm.reads[1])
        self.assertTrue(self.pm.reads[0]['WithDecryption'])
    def test_parameter_access_error_never_reads_stale_secret(self):
        self.pm.error=PermissionError('denied')
        with self.assertRaises(PermissionError):self.reader.get_secret_value(SecretId=module._LOCATIONS[0]['sourceArn'])
        self.assertFalse(self.sm.reads)
    def test_dynamic_reads_and_writes_unchanged(self):
        self.assertEqual(self.reader.get_secret_value(SecretId='arn:aws:secretsmanager:us-east-1:820323452649:secret:heytim/connections/user-token')['SecretString'],'dynamic')
        self.assertEqual(self.reader.put_secret_value(SecretId='dynamic',SecretString='rotated'),{'VersionId':'updated'})
        self.assertFalse(self.pm.reads)
    def test_short_name_requires_exact_account(self):
        with patch.dict(os.environ,{'HEYTIM_CREDENTIAL_ACCOUNT_ID':'820323452649'}):self.reader.get_secret_value(SecretId='heytim/stripe/production')
        self.assertIn(':820323452649:parameter/',self.pm.reads[-1]['Name'])
    def test_version_requests_do_not_silently_change_meaning(self):
        with self.assertRaises(ValueError):self.reader.get_secret_value(SecretId=module._LOCATIONS[0]['sourceArn'],VersionStage='AWSPREVIOUS')
        self.assertFalse(self.pm.reads)
    def test_mappings_remain_in_original_account_and_region(self):
        for row in module._LOCATIONS:self.assertEqual(row['sourceArn'].split(':')[3:5],row['parameterArn'].split(':')[3:5])
if __name__=='__main__':unittest.main()
