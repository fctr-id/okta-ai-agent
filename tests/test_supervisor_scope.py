"""Empty intermediate evidence must not override a scope clarification or next step."""
import unittest
from unittest.mock import patch
from pydantic_ai.models.test import TestModel


class ScopeTests(unittest.TestCase):
    def test_unresolved_scope_cannot_delegate_or_reuse(self):
        with patch('src.core.models.model_picker.ModelConfig.get_model', return_value=TestModel()):
            from src.core.agents.supervisor_agent import SupervisorDecision
        for mode, target in [('delegate', 'SQL'), ('complete', 'SYNTHESIS'), ('empty', 'NONE')]:
            decision = SupervisorDecision(mode=mode, target=target, reasoning='Missing user criteria',
                                          scope_questions=['Which time period should I use?'],
                                          reuse_procedure_id='candidate', adapt_procedure=True)
            self.assertEqual(decision.mode, 'clarify')
            self.assertEqual(decision.target, 'NONE')
            self.assertIsNone(decision.reuse_procedure_id)
            self.assertFalse(decision.adapt_procedure)
            self.assertEqual(decision.user_message, 'Which time period should I use?')

    def test_empty_intermediate_preserves_supervisor_choice(self):
        with patch('src.core.models.model_picker.ModelConfig.get_model', return_value=TestModel()):
            from src.core.agents.supervisor_agent import SupervisorDecision, _normalize_after_delegation_decision
            from src.data.schemas.artifact_manifest import DelegationResult
        evidence = DelegationResult(source_specialist='sql', success=True, status='empty',
                                    result_mode='empty', summary='No matching rows', artifact_keys=['fixture'],
                                    result_set_refs=['ref'])
        for mode, target in [('clarify', 'NONE'), ('delegate', 'API'), ('delegate', 'SQL'), ('empty', 'NONE')]:
            with self.subTest(mode=mode, target=target):
                decision = SupervisorDecision(mode=mode, target=target, reasoning='Scope requires this step',
                                              requested_data=['Resolve the remaining requirement'])
                normalized = _normalize_after_delegation_decision(decision, evidence)
                self.assertEqual((normalized.mode, normalized.target), (mode, target))

    def test_completion_with_empty_evidence_still_reports_empty(self):
        with patch('src.core.models.model_picker.ModelConfig.get_model', return_value=TestModel()):
            from src.core.agents.supervisor_agent import SupervisorDecision, _normalize_after_delegation_decision
            from src.data.schemas.artifact_manifest import DelegationResult
        evidence = DelegationResult(source_specialist='sql', success=True, status='empty',
                                    result_mode='empty', summary='All requirements resolved', artifact_keys=['fixture'])
        decision = SupervisorDecision(mode='complete', target='SYNTHESIS', reasoning='No matching rows')
        self.assertEqual(_normalize_after_delegation_decision(decision, evidence).mode, 'empty')


if __name__ == '__main__':
    unittest.main()
