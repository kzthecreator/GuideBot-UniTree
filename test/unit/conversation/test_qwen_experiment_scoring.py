"""Guard offline experiment metrics against false successes, independent of Qwen."""
import unittest
from test.experiments.gesture.evaluate_qwen_semantics import locate, score

class ExperimentScoringTests(unittest.TestCase):
    def setUp(self):
        self.case={'text':'先说左侧展台，再请看左侧展台。','gold':{'acceptable_action_sets':[['left_show']]}}
        self.mapping={'left_show':'x','right_show':'y'}
    def output(self, begin, finish):
        return {'actions':[{'action':'x','begin':begin,'finish_by':finish}]}
    def test_wrong_occurrence_is_not_silently_relocated(self):
        with self.assertRaises(ValueError):locate(self.case['text'],{'text':'左侧展台','occurrence':3})
        self.assertEqual(locate(self.case['text'],{'text':'左侧展台','occurrence':2}),(10,14))
    def test_reverse_quotes_fail_even_when_action_is_correct(self):
        r=score(self.case,self.output({'text':'左侧展台','occurrence':2},{'text':'先说','occurrence':1}),self.mapping,'J',False)
        self.assertTrue(r['action_set_correct']);self.assertFalse(r['mechanical_pass'])
    def test_all_empty_does_not_pass_positive(self):
        self.assertFalse(score(self.case,{'actions':[]},self.mapping,'J',False)['mechanical_pass'])
    def test_valid_quotes_do_not_make_wrong_action_correct(self):
        r=self.output({'text':'再请看','occurrence':1},{'text':'左侧展台','occurrence':2});r['actions'][0]['action']='y'
        out=score(self.case,r,self.mapping,'J',False)
        self.assertTrue(out['format_and_quotes_valid']);self.assertFalse(out['mechanical_pass'])
    def test_bad_first_quote_does_not_hide_later_action_selection(self):
        case=dict(self.case,gold={'acceptable_action_sets':[['left_show','right_show']]})
        value=self.output({'text':'不存在','occurrence':1},{'text':'展台','occurrence':1})
        second=dict(value['actions'][0],action='y');value['actions'].append(second)
        r=score(case,value,self.mapping,'J',False)
        self.assertTrue(r['action_set_correct']);self.assertFalse(r['mechanical_pass'])
    def test_real_binding_and_stricter_experiment_are_distinguished(self):
        value=self.output({'text':'先说左侧','occurrence':1},{'text':'左侧展台','occurrence':1})
        r=score(self.case,value,self.mapping,'J',False)
        self.assertFalse(r['mechanical_pass']);self.assertTrue(r['production_binding_pass'])
    def test_unknown_id_does_not_disappear_into_an_empty_prediction(self):
        case=dict(self.case,gold={'acceptable_action_sets':[[]]})
        value=self.output({'text':'先说','occurrence':1},{'text':'展台','occurrence':1})
        value['actions'][0]['action']='not_in_dictionary'
        r=score(case,value,self.mapping,'J',False)
        self.assertTrue(r['predicted']);self.assertFalse(r['action_set_correct'])
        self.assertFalse(r['production_binding_pass'])
    def test_do_not_split_english_words(self):
        with self.assertRaises(ValueError):locate('请看 Smart Hub 展台',{'text':'mart','occurrence':1})
    def test_none_classifier_and_task_override(self):
        self.case['task_gold_override']={'selection':[['left_show']],'joint':[[]]}
        self.assertTrue(score(self.case,{'actions':[]},self.mapping,'J',False)['mechanical_pass'])
        self.assertFalse(score(self.case,{'label':'none'},self.mapping,'C',False)['mechanical_pass'])

if __name__=='__main__':unittest.main()
