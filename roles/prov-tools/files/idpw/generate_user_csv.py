import csv
import requests

base_url = 'http://idm3-bindbroker:8090/IDManager'
user_url = base_url + '/userEditorInterface'
user_group_url = base_url + '/SystemUserGroupIF'
req_header = {'HTTP_SYSTEMACCOUNT': 'SYSTEM'}

def find_user_group(gid, user_group):
    rl = list(filter(lambda x: gid in map(lambda y: y['id'], x['ou']), user_group))
    return rl[0] if len(rl) > 0 else {'sAMAccountName':'', 'gidNumber':''}


if __name__=="__main__":
    user_req = requests.get(user_url, headers=req_header)
    user_group_req = requests.get(user_group_url, headers=req_header)
    user = user_req.json()
    user_group = user_group_req.json()
    with open('user.csv', mode='w', encoding='utf-8', newline='') as file:
        writer = csv.writer(file)
        header = ['sn','givenName','displayName','mail','company','department','sAMAccountName','uidNumber','organizationalUnit','gidNumber','userPrincipalName']
        writer.writerow(header)
        for u in user:
            ug = find_user_group(u['team'],user_group)
            row = [
                u['sn'],
                u['cn'],
                u['displayName'],
                u['email2'],
                u['companyName'],
                u['department'],
                u['sAMAccountName'],
                u['uidNumber'],
                ug['sAMAccountName'],
                ug['gidNumber'],
                u['email']
            ]
            writer.writerow(row)
