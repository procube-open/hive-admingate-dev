# coding: utf-8
#!/usr/bin/python
import boto3
from botocore.exceptions import ClientError
from ansible.module_utils.basic import AnsibleModule

# client を使用
# リトライ機能は boto3 に任せる。AWS 設定ファイル (~/.aws/config) による設定を行う。リトライ数などのログもboto3で出力される（ただしDebugレベル）
iam_client = boto3.client('iam')

def disable_role(module, role_name, resourceTagKey, resourceTagDisabledValue):
    """
    Disables a role.

    :param AnsibleModule module: To use module logging
    :param string role_name: The name of the role.
    :param string resourceTagKey: Key-name of aws:ResourceTag.
    :param string resourceTagDisabledValue: Value of aws:ResourceTag. The value to disable the role.
    :return: The disabled role.
    :rtype: dict
    """

    # 既存のタグを取得
    try:
        response_role = iam_client.get_role(RoleName=role_name)
        existing_tags = response_role.get('Role', {}).get('Tags', [])
    except iam_client.exceptions.NoSuchEntityException:
        module.debug(f"Couldn't find the role. Role '{role_name}' does not exist.")
        raise
    except Exception as e:
        module.debug(f"Couldn't find the role '{role_name}'. Error:{e}")
        raise
    
    # 削除するタグのキーのリスト作成。タグがない場合は空のリスト
    keys_to_remove = []
    for tag in existing_tags:
        keys_to_remove.append(tag["Key"])
    
    # 既存のタグを削除
    if keys_to_remove:
        try:
            iam_client.untag_role(
                RoleName=role_name,
                TagKeys=keys_to_remove
            )
            module.debug(f"The tag '{keys_to_remove}' was removed from role '{role_name}'.")
        except Exception as e:
            module.debug(f"Couldn't delete tags '{keys_to_remove}'. Error:{e}")
            raise

    # ロールのタグ値を上書き（無効にするため、タグ値を無効値に設定する）
    try:
        response = iam_client.tag_role(
            RoleName=role_name,
            Tags=[
                {
                    'Key': resourceTagKey,
                    'Value': resourceTagDisabledValue
                }
            ]
        )
    except iam_client.exceptions.NoSuchEntityException:
        module.debug(f"Couldn't update tags. Role '{role_name}' does not exist.")
        raise
    except ClientError as e:
        module.debug(f"Couldn't update tags of '{role_name}'. Error:{e}")
        raise

    return response

def main():
    module = AnsibleModule(
        argument_spec=dict(
            roleName=dict(
                type="str",
                required=True
            ),
            resourceTagKey=dict(
                type="str",
                required=True
            ),
            resourceTagDisabledValue=dict(
                type="str",
                required=True
            )
        )
    )
    pRoleName = module.params["roleName"]
    pResourceTagKey = module.params["resourceTagKey"]
    pResourceTagDisabledValue = module.params["resourceTagDisabledValue"]

    # 作業ロールを無効化
    try:
        response = disable_role(module, pRoleName, pResourceTagKey, pResourceTagDisabledValue)
        module.debug(f"Updated the tag value to an invalid value. The role is '{pRoleName}'.")
    except ClientError as e:
        module.fail_json(msg=f"Failed to update the tag value. ClientError detail: {e}", changed=False, role=pRoleName)
        return
    except Exception as e:
        module.fail_json(msg=f"Failed to update the tag value. Exception detail: {e}", changed=False, role=pRoleName)
        return

    module.exit_json(changed=True, msg="Updated the tag value to an invalid value.", role=pRoleName)

if __name__ == "__main__":
    main()
