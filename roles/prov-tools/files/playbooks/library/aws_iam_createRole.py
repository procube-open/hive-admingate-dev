# coding: utf-8
#!/usr/bin/python
import json
import boto3
from botocore.exceptions import ClientError
from ansible.module_utils.basic import AnsibleModule

# client を使用
# リトライ機能は boto3 に任せる。AWS 設定ファイル (~/.aws/config) による設定を行う。リトライ数などのログもboto3で出力される（ただしDebugレベル）
iam_client = boto3.client('iam')

def create_role(module, role_name, resourceTagKey, resourceTagValue, workUsers, workUserGroups, periods, principalArn):
    """
    Creates a role.

    :param AnsibleModule module: To use module logging
    :param string role_name: The name of the role.
    :param string resourceTagKey: Key-name of aws:ResourceTag.
    :param string resourceTagValue: Value of aws:ResourceTag.
    :param list(string) workUsers: List of work users allowed access to the role.
    :param list(string) workUserGroups: List of work userGroups allowed access to the role.
    :param list(dict) periods: Validity period of the role.
    :param string principalArn: Principal ARN of the trust policy.
    :return: The newly created role.
    :rtype: dict
    """

    statement = []
    base_statement = {
        "Effect": "Allow",
        "Principal": {
            "AWS": principalArn
        },
        "Action": "sts:AssumeRole",
        "Condition": {
            "StringEquals": {
                "aws:ResourceTag/"+resourceTagKey: resourceTagValue,
                "aws:PrincipalTag/AdminGateAccess": "true"
                # Dynamically add here. "saml:sub": workers
            },
            # Dynamically add here.
            # StringLike: { "aws:PrincipalTag/AdminGateTeam": workUserGroups }
            "DateLessThanEquals": {
                "aws:CurrentTime": periods[0]["validUntil"]
            },
            "DateGreaterThanEquals": {
                "aws:CurrentTime": periods[0]["validFrom"]
            }
        }
    }

    if workUsers and len(workUsers) != 0:
        conditionOperator = "StringEquals"
        saml_sub = {"saml:sub": workUsers}
        generatedStatement = generate_statement(base_statement, conditionOperator, saml_sub, "StatementWorkUsers")
        statement.append(generatedStatement)

    if workUserGroups and len(workUserGroups) != 0:
        newWorkUserGroups = []
        for group in workUserGroups:
            newWorkUserGroups.append(f"*:{group}:*")
        saml_groups = {"aws:PrincipalTag/AdminGateTeam": newWorkUserGroups}
        conditionOperator = "StringLike"
        generatedStatement = generate_statement(base_statement, conditionOperator, saml_groups, "StatementWorkUserGroups")
        statement.append(generatedStatement)

    if len(statement) == 0:
        module.debug(f"There are no users or groups to allow. Role is '{role_name}'.")
        raise Exception(f"There are no users or groups to allow. Role is '{role_name}'.")

    # CreateRole アクションの信頼関係ポリシー
    assumeRolePolicyDocument = {
        "Version": "2012-10-17",
        "Statement": statement
    }

    try:
        response = iam_client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(assumeRolePolicyDocument), # ensure_ascii=False
            Tags=[
                {
                    'Key': resourceTagKey,
                    'Value': resourceTagValue
                }
            ]
        )
    except iam_client.exceptions.EntityAlreadyExistsException:
        module.debug(f"Couldn't create a role. Role '{role_name}' already exists.")
        raise
    except ClientError as e:
        module.debug(f"Couldn't create role {role_name}. Error:{e}")
        raise

    return response


def generate_statement(base_statement: dict, conditionOperator: str, string_equals_additions: dict, sid: str) -> dict:
    """
    Generates a statement of the trust policy. 
    Dynamically add a StringEquals condition.

    :param dict base_statement: Base statement's object.
    :param string conditionOperator: Specify a condition operator to add context.
    :param dict string_equals_additions: Add StringEquals's object. ex. {"saml:sub": ["user1", "user2"]}
    :param string sid: Sid value.
    :return: The generated statement.
    :rtype: dict
    """

    # ディープコピーをして元の辞書を変更しないようにする
    statement = json.loads(json.dumps(base_statement))

    if "Condition" not in statement:
        statement["Condition"] = {}

    if conditionOperator not in statement["Condition"]:
        statement["Condition"][conditionOperator] = {}

    # StringEquals or StringLike に動的な要素を追加
    statement["Sid"] = sid
    statement["Condition"][conditionOperator].update(string_equals_additions)

    return statement


def attach_policy_to_role(module, role_name, policy_name, policyArnPrefix):
    """
    Attaches a policy to a role.

    :param AnsibleModule module: To use module logging
    :param role_name: The name of the role. **Note** this is the name, not the ARN.
    :param policy_name: The name of the policy. **Note** this is the name, not the ARN.
    :param policyArnPrefix: ARN prefix of the policy.
    :return: The attached policy ARN.
    :rtype: string
    """

    try:
        policy_arn = f'{policyArnPrefix}{policy_name}'
        iam_client.attach_role_policy(
            RoleName=role_name,
            PolicyArn=policy_arn
        )
    except iam_client.exceptions.NoSuchEntityException:
        module.debug(f"Role '{role_name}' or policy '{policy_name}' not found.")
        raise
    except ClientError as e:
        module.debug(f"Couldn't attach policy '{policy_name}' to role '{role_name}'. Error:{e}")
        raise

    return policy_arn


def rollback(module, role_name, attachedPolicyARNs, policyArnPrefix):
    """
    Rollback. Detach the policies and delete the role.

    :param AnsibleModule module: To use module logging
    :param string role_name: The name of the role.
    :param list(string) attachedPolicyARNs: List of attached policyARN.
    """

    module.debug(f"Start rollback process for {role_name}.")

    if attachedPolicyARNs:
        for policy_arn in attachedPolicyARNs:
            policy_name = policy_arn[len(policyArnPrefix):]
            try:
                module.debug(f"Start process to detach policy '{policy_name}'.")
                iam_client.detach_role_policy(
                    RoleName=role_name,
                    PolicyArn=policy_arn
                )
                module.debug(f"Finished process to detach policy '{policy_name}'.")
            except Exception as e:
                module.debug(f"Couldn't detach policy '{policy_name}'. Error: {e}")
                raise
        
    if role_name:
        try:
            module.debug(f"Start process to delete role '{role_name}'.")
            iam_client.delete_role(
                RoleName=role_name
            )
            module.debug(f"Finished process to delete role '{role_name}'.")
        except Exception as e:
            module.debug(f"Couldn't delete role '{role_name}'. Error: {e}")
            raise
        
    module.debug(f"Finished rollback process for {role_name}.")


def main():
    module = AnsibleModule(
        argument_spec=dict(
            roleName=dict(
                type="str",
                required=True
                #no_log=True # sample: passwordなどのとき
            ),
            resourceTagKey=dict(
                type="str",
                required=True
            ),
            resourceTagValue=dict(
                type="str",
                required=True
            ),
            workUsers=dict(
                type="list",
                elements="str",
                required=True
            ),
            workUserGroups=dict(
                type="list",
                elements="str",
                required=True
            ),
            periods=dict(
                type="list",
                elements="dict",
                required=True
            ),
            principalArn=dict(
                type="str",
                required=True
            ),
            policyArnPrefix=dict(
                type="str",
                required=True
            ),
            iamPolicies=dict(
                type="list",
                elements="str",
                required=True
            )
        )
    )
    pRoleName = module.params["roleName"]
    pResourceTagKey = module.params["resourceTagKey"]
    pResourceTagValue = module.params["resourceTagValue"]
    pWorkUsers = module.params["workUsers"]
    pWorkUserGroups = module.params["workUserGroups"]
    pPeriods = module.params["periods"]
    pPrincipalArn = module.params["principalArn"]
    pPolicyArnPrefix = module.params["policyArnPrefix"]
    pIamPolicies =  module.params["iamPolicies"]

    createdRoleName = None
    attachedPolicyNames = []
    attachedPolicyARNs = []

    # 作業ロールを作成。失敗時は基本ロールバックは不要
    try:
        response = create_role(module, pRoleName, pResourceTagKey, pResourceTagValue, pWorkUsers, pWorkUserGroups, pPeriods, pPrincipalArn)
        createdRoleName = response["Role"]["RoleName"]
        module.debug(f"Created role '{createdRoleName}', with trust policy:")
    except ClientError as e:
        module.fail_json(msg=f"Failed to create a role. ClientError detail: {e}", changed=False, role=pRoleName)
        return
    except Exception as e:
        module.fail_json(msg=f"Failed to create a role. Exception detail: {e}", changed=False, role=pRoleName)
        return


    # ポリシーをアタッチ。失敗時はロールバック処理を実行
    try:
        for policy_name in pIamPolicies:
            createdPolicyArn = attach_policy_to_role(module, createdRoleName, policy_name, pPolicyArnPrefix)
            module.debug(f"Attached policy '{policy_name}' to '{createdRoleName}'.")

            attachedPolicyNames.append(policy_name)
            attachedPolicyARNs.append(createdPolicyArn)
        
        module.exit_json(changed=True, msg="Created role with trust policy, and attached policies.", role=createdRoleName, attachedPolicies=attachedPolicyNames)

    except Exception as e:
        try:
            rollback(module, createdRoleName, attachedPolicyARNs, pPolicyArnPrefix)
        except Exception as rollback_err:
            module.fail_json(
                msg=f"Failed to attach policies, and failed to rollback. [Caution] The role may remain. Exception detail(attachPolicy): {e}, Exception detail(rollback): {rollback_err}",
                changed=True,
                role=pRoleName,
                attachedPolicies=attachedPolicyNames
            )
        
        module.fail_json(msg=f"Failed to attach policies. The registered role has been deleted (rolled back). Exception detail: {e}", changed=False, role=pRoleName, attachedPolicies=attachedPolicyNames)

if __name__ == "__main__":
    main()
