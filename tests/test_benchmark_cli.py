"""The public experiment entry point must generate configs without lab paths or GPUs."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class BenchmarkCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.repo=Path(__file__).resolve().parents[1]
        self.model=self.root/'model';self.model.mkdir()
        (self.model/'config.json').write_text('{}')

    def tearDown(self):self.tmp.cleanup()

    def command(self, out, *options):
        return subprocess.run([sys.executable,str(self.repo/'scripts/benchmark.py'),
            '--model-dir',str(self.model),'--engine-python',sys.executable,
            '--out',str(out),'--plan-only',*options],cwd=self.repo,
            env=dict(os.environ,PYTHONPATH=str(self.repo/'src')),capture_output=True,text=True)

    def test_explicit_model_environment_and_resource_plans(self):
        for mode,gpus in [('single',['0']),('replicas',['0','1']),('nccl',['0','1'])]:
            out=self.root/mode
            result=self.command(out,'--mode',mode,'--gpus',*gpus,'--smoke')
            self.assertEqual(result.returncode,0,result.stderr)
            spec=json.loads((out/'campaign.json').read_text())
            self.assertIsNone(spec['model_source_lock'])
            self.assertEqual(len(spec['deployment_configs']),len(gpus))
            for path in spec['deployment_configs']:
                engine=json.loads(Path(path).read_text())
                args=engine['serve_command']
                self.assertEqual(args[0],str(Path(sys.executable).resolve()))
                self.assertEqual(args[args.index('--model')+1],str(self.model.resolve()))
                self.assertNotIn('model_source_lock',engine)

    def test_optional_source_lock_preserved(self):
        lock=self.model/'SOURCE_LOCK.json';lock.write_text('{}')
        out=self.root/'locked'
        result=self.command(out,'--mode','single','--gpus','0','--smoke')
        self.assertEqual(result.returncode,0,result.stderr)
        spec=json.loads((out/'campaign.json').read_text())
        self.assertEqual(spec['model_source_lock'],str(lock))
        engine=json.loads(Path(spec['deployment_configs'][0]).read_text())
        self.assertEqual(engine['model_source_lock'],str(lock))

    def test_invalid_gpu_sets_and_ports_fail_before_outputs(self):
        variants=[['--mode','single','--gpus','0','1'],
                  ['--mode','nccl','--gpus','0','0'],
                  ['--mode','single','--gpus','-1'],
                  ['--mode','single','--gpus','0','--port-base','65500']]
        for i,options in enumerate(variants):
            out=self.root/f'invalid-{i}'
            result=self.command(out,*options)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse(out.exists())
