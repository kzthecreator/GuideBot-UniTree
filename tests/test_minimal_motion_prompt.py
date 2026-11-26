import json
from pathlib import Path
import unittest
from unittest.mock import patch

from GuideBot.gesture.catalog import Catalog,DIRECTORY,make_input,messages,minimal_document
from GuideBot.gesture.planner import Planner


class MinimalPromptTests(unittest.TestCase):
    def setUp(self):
        self.catalog=Catalog()
        self.payload=dict(make_input('r','大家好，介绍一下这台机器人。',complete=True),
                          timing_contract='semantic_keyframes',playback_elapsed_s=0.,
                          playback_started=False,suggested_planning_lead_s=2.)

    def test_only_three_action_fields_and_active_ids(self):
        document=minimal_document(self.catalog)
        self.assertEqual({a['id'] for a in document['actions']},set(self.catalog.actions))
        for row in document['actions']:
            self.assertEqual(set(row),{'id','description','minimum_duration_s'})
            timing=self.catalog.execution_timing(row['id'])
            floor=timing.get('minimum_total_ms',max(0.,timing['minimum_remaining_s']-timing['reserved_overhead_s'])*1000)/1000
            self.assertGreaterEqual(row['minimum_duration_s']+1e-9,floor)
            self.assertLessEqual(row['minimum_duration_s']-floor,.001000001)
        rows={row['id']:row for row in document['actions']}
        self.assertNotIn('欢迎',rows['B_Open_Hold']['description'])
        self.assertIn('双肘弯曲',rows['B_Neutral_Rest']['description'])
        self.assertNotIn('L_Center_Rest',rows)

    def test_no_old_semantic_rules_or_few_shots_in_default(self):
        with patch.dict('os.environ',{'GUIDEBOT_GESTURE_PROMPT':'minimal'}):
            prompt=messages(self.catalog,self.payload)
        self.assertEqual(len(prompt),2)
        self.assertNotIn('{{',prompt[0]['content'])
        self.assertNotIn('interaction_functions',prompt[0]['content'])
        self.assertNotIn('when_to_use',prompt[0]['content'])
        self.assertNotIn('普通事实陈述',prompt[0]['content'])
        self.assertIn('keyframes',prompt[0]['content'])
        self.assertNotIn('额外预留',prompt[0]['content'])
        self.assertNotIn('0.65 秒',prompt[0]['content'])
        self.assertTrue(all(self.catalog.execution_timing(name)['reserved_overhead_s']==0 for name in self.catalog.actions))
        self.assertEqual(json.loads(prompt[-1]['content']),self.payload)

    def test_removed_original_rejected(self):
        with self.assertRaises(ValueError):
            messages(self.catalog,self.payload,prompt_variant='original')
        with patch.dict('os.environ',{'GUIDEBOT_GESTURE_PROMPT':'original'}):
            with self.assertRaises(ValueError):messages(self.catalog,self.payload)

    def test_stale_description_not_applied_to_rerecorded_asset(self):
        self.catalog.assets['B_Neutral_Rest']['metadata']['sha256']='different recording'
        row=next(r for r in minimal_document(self.catalog)['actions'] if r['id']=='B_Neutral_Rest')
        self.assertEqual(row['description'],self.catalog.actions['B_Neutral_Rest']['description'])

    def test_bad_variant_and_legacy_contract_rejected(self):
        with self.assertRaises(ValueError):messages(self.catalog,self.payload,prompt_variant='unknown')
        legacy=make_input('r','欢迎来到展厅。')
        with self.assertRaises(ValueError):messages(self.catalog,dict(legacy,timing_contract='fixed_deadline'))
        with self.assertRaises(ValueError):messages(self.catalog,legacy,prompt_variant='minimal')

    def test_planner_sends_minimal_prompt_and_validates_stream_offline(self):
        from unittest.mock import Mock
        name='L_Short_Nudge' if 'L_Short_Nudge' in self.catalog.actions else 'B_Open_Hold'
        row=dict(action=name,keyframes=[dict(frame=self.catalog.assets[name]['frames']-1,unit=1)],hold_s=0.)
        response=Mock(status_code=200)
        response.__enter__=Mock(return_value=response)
        response.__exit__=Mock(return_value=False)
        packet=dict(choices=[dict(delta=dict(content=json.dumps(dict(actions=[row]))),finish_reason='stop')])
        response.iter_lines.return_value=['data: '+json.dumps(packet),'data: [DONE]']
        http=Mock();http.post.return_value=response
        planner=Planner(self.catalog,api_key='offline',session=http)
        plans=[]
        with patch.dict('os.environ',{'GUIDEBOT_GESTURE_PROMPT':'minimal'}):
            stats=planner.plan(self.payload,plans.append)
        self.assertEqual(stats['valid_actions'],1)
        self.assertEqual(plans[0].action,name)
        sent=http.post.call_args.kwargs['json']['messages'][0]['content']
        self.assertIn('minimum_duration_s',sent)
        self.assertNotIn('interaction_functions',sent)


if __name__=='__main__':unittest.main()
