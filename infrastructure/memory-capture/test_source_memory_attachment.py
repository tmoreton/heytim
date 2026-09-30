"""Fail-closed checks for the legacy source Memory change-set planner."""

import copy
from pathlib import Path
import tempfile
import unittest

import source_memory_attachment as attach


class SourceMemoryAttachmentTests(unittest.TestCase):
    def setUp(self):
        self.config = attach.load_config()
        self.template = {
            "Parameters": {"BootstrapVersion": {"Type": "String"}},
            "Resources": {
                self.config["memoryLogicalId"]: {
                    "Type": attach.MEMORY_TYPE,
                    "Properties": {"Name": self.config["memoryName"],
                                   "EventExpiryDuration": self.config["memoryEventExpiryDays"]}},
                "OtherResource": {"Type": "AWS::Logs::LogGroup", "Properties": {"RetentionInDays": 30}},
            },
        }
        self.config["expectedTemplateSha256"] = attach.sha256(self.template)
        self.stack = {"Capabilities": ["CAPABILITY_NAMED_IAM"], "RoleARN": "arn:aws:iam::188757775631:role/cfn",
                      "Parameters": [{"ParameterKey": "BootstrapVersion", "ParameterValue": "32"}]}
        self.change_set = {
            "StackId": self.config["sourceStackId"],
            "ChangeSetType": "UPDATE",
            "Status": "CREATE_COMPLETE",
            "ExecutionStatus": "AVAILABLE",
            "RoleARN": "arn:aws:iam::188757775631:role/cfn",
            "Capabilities": ["CAPABILITY_NAMED_IAM"],
            "Parameters": [{"ParameterKey": "BootstrapVersion", "ParameterValue": "32"}],
            "Changes": [{"Type": "Resource", "ResourceChange": {
                "Action": "Modify", "LogicalResourceId": self.config["memoryLogicalId"],
                "PhysicalResourceId": self.config["memoryArn"], "ResourceType": attach.MEMORY_TYPE,
                "Replacement": "False", "Scope": ["Properties"],
                "Details": [{"Evaluation": "Static", "ChangeSource": "DirectModification",
                             "Target": {"Attribute": "Properties", "Name": "StreamDeliveryResources",
                                        "Path": "/Properties/StreamDeliveryResources",
                                        "AttributeChangeType": "Add", "RequiresRecreation": "Never"}}],
            }}],
        }

    def test_candidate_changes_only_source_stream_property(self):
        original = copy.deepcopy(self.template)
        candidate = attach.build_candidate(self.template, self.config)
        self.assertEqual(self.template, original)
        self.assertEqual(candidate["Resources"][self.config["memoryLogicalId"]]["Properties"]
                         ["StreamDeliveryResources"], self.config["streamDeliveryResources"])
        self.assertEqual(candidate["Resources"]["OtherResource"], original["Resources"]["OtherResource"])
        with tempfile.TemporaryDirectory() as directory:
            path = attach.create_private_plan(candidate, Path(directory))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)

    def test_template_or_identity_drift_fails_closed(self):
        wrong = copy.deepcopy(self.template)
        wrong["Resources"]["OtherResource"]["Properties"]["RetentionInDays"] = 31
        with self.assertRaisesRegex(ValueError, "drifted"):
            attach.build_candidate(wrong, self.config)
        wrong = copy.deepcopy(self.template)
        wrong["Resources"][self.config["memoryLogicalId"]]["Properties"]["StreamDeliveryResources"] = {}
        self.config["expectedTemplateSha256"] = attach.sha256(wrong)
        with self.assertRaisesRegex(ValueError, "already has stream"):
            attach.build_candidate(wrong, self.config)

    def test_only_exact_in_place_change_set_passes(self):
        attach.validate_change_set(self.change_set, self.config, self.stack)
        for mutation in (
            lambda x: x["Changes"].append(copy.deepcopy(x["Changes"][0])),
            lambda x: x["Changes"][0]["ResourceChange"].update(Replacement="Conditional"),
            lambda x: x["Changes"][0]["ResourceChange"]["Details"][0]["Target"].update(Name="Name"),
            lambda x: x["Changes"][0]["ResourceChange"]["Details"][0]["Target"].update(Path="/Properties/Name"),
            lambda x: x["Changes"][0]["ResourceChange"]["Details"][0].update(Evaluation="Dynamic"),
            lambda x: x["Changes"][0]["ResourceChange"].update(PhysicalResourceId="other-memory"),
            lambda x: x["Parameters"][0].update(ParameterValue="33"),
            lambda x: x.update(RoleARN="arn:aws:iam::188757775631:role/other"),
            lambda x: x.update(NextToken="truncated"),
        ):
            with self.subTest(mutation=mutation):
                bad = copy.deepcopy(self.change_set)
                mutation(bad)
                with self.assertRaises(ValueError):
                    attach.validate_change_set(bad, self.config, self.stack)

    def test_memory_contract_ignores_service_timestamps_but_not_configuration(self):
        memory = {"id": self.config["memoryId"], "arn": self.config["memoryArn"],
                  "name": self.config["memoryName"], "eventExpiryDuration": 30,
                  "strategies": [{"strategyId": "one", "type": "SEMANTIC", "status": "ACTIVE",
                                  "updatedAt": "now", "namespaces": ["/facts/{actorId}/"]}]}
        baseline = attach.sha256(attach.memory_contract(memory))
        memory["updatedAt"] = "later"
        memory["strategies"][0]["updatedAt"] = "later"
        self.assertEqual(attach.sha256(attach.memory_contract(memory)), baseline)
        memory["strategies"][0]["namespaces"] = ["/other/"]
        self.assertNotEqual(attach.sha256(attach.memory_contract(memory)), baseline)


if __name__ == "__main__":
    unittest.main()
