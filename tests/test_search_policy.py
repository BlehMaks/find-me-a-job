import unittest
from fmj.campaign import screen_opportunity
from fmj.records import opportunity_key


class SearchPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = {"id":"test", "version":1, "approved":True, "approved_titles":["Researcher"],
            "hard_exclusions":{"employers":["Excluded Company GmbH"], "duties":["people management"]},
            "resource_classes":["official"], "expansion_authority":False,
            "allowed_locations":["Example City"], "disliked_duties":["frequent travel"]}
        self.role = {"employer":"Synthetic Lab", "title":"Researcher", "duties":["Study materials"],
                     "location":"Example City", "resource_class":"official"}

    def test_title_does_not_override_excluded_duties(self):
        self.role["duties"] = ["Research and people management"]
        self.assertEqual(screen_opportunity(self.policy, self.role)["decision"], "excluded")

    def test_disclosed_end_employer_legal_suffix_variants(self):
        self.role["end_employer"] = "EXCLUDED COMPANY, GmbH."
        self.assertEqual(screen_opportunity(self.policy, self.role)["decision"], "excluded")

    def test_conflicting_location_and_source_expansion(self):
        self.role["location"] = "Other City"
        self.assertEqual(screen_opportunity(self.policy, self.role)["decision"], "needs_confirmation")
        self.role["location"] = "Example City"
        self.role.update(title="Adjacent Researcher", resource_class="academic-group")
        self.assertEqual(screen_opportunity(self.policy, self.role)["decision"], "needs_confirmation")
        self.policy["expansion_authority"] = True
        self.assertEqual(screen_opportunity(self.policy, self.role)["decision"], "eligible")
        self.policy["contradictions"] = ["Unresolved location requirement"]
        self.assertEqual(screen_opportunity(self.policy, self.role)["decision"], "needs_confirmation")

    def test_flexible_dislike_is_disclosed_not_a_hard_exclusion(self):
        self.role["duties"] = ["Occasional frequent travel"]
        result = screen_opportunity(self.policy, self.role)
        self.assertEqual(result["decision"], "eligible")
        self.assertEqual(result["preferences"], ["frequent travel"])

    def test_canonical_requisition_survives_discovery_channel(self):
        self.assertEqual(opportunity_key("Synthetic Lab", "REQ1", "https://one.invalid/a"), opportunity_key("synthetic lab", "req1", "https://two.invalid/b"))
        self.assertNotEqual(opportunity_key("Synthetic Lab", "REQ1"), opportunity_key("Synthetic Lab", "REQ2"))
