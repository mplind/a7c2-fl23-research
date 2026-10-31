"""Complete names + EBUSY pauses before programs and supports cold continuation."""
import contextlib,copy,json,struct,tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from looktool import checkpointworker,direct,lookfile,nameworker,namespause,resources
from test_checkpoint import Camera,values,fake_compile
from test_direct import SimDirect


class NamesPauseTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.forward_calls=[]  # the modes of each forward_names call look_write sees
        self.root=Path(tmp.name);self.failed=self.root/'failed';(self.failed/'evidence').mkdir(parents=True)
        self.current=values();self.camera=Camera(self.current)
        self.camera.usr_mount_readonly=False;self.camera.boot='boot-old'
        self.target=dict(self.current,**{'appFw.so':b'\7'+self.current['appFw.so'][1:]})
        with patch.object(checkpointworker,'compile_worker',side_effect=fake_compile):
            programs=checkpointworker.build_programs(self.current,self.target,self.failed/'worker')
        rows=[]
        for n in nameworker.filenames():
            old=self.current['resources/'+n];new,plan=resources.rename(old,{1:'CC'})
            self.camera.files['/usr/share/app/'+n]=new
            rows.append(dict(file=n,before_bytes=len(old),after_bytes=len(new),inverse=plan))
        path=self.failed/'names/names.so';path.parent.mkdir();path.write_bytes(b'known names worker')
        path.with_name('names.private.h').write_text('static const u32 label_ids[]={'+','.join(str(v)+'U' for v in resources.LABEL_IDS)+'};\n')
        self.build=dict(path=str(path),count=68,files=rows,byte_only=True,stream_install=True,AP=None)
        self.raw=nameworker.REPORT.pack(b'A7NMR001',1,1,9,68,-16,0,0,-16,0,0,517,68,0,68,0,0,0,bytes(32))
        (self.failed/'evidence/failed-names-forward-1.bin').write_bytes(self.raw)
        lookfile.write(self.failed/'reference.a7look','CC',bytes(1215),method='fixture',attribution='test')
        self.state=dict(schema='a7c2-direct-job/1',phase='NEEDS_REVIEW',mode='look_import',slot=1,name='CC',
            identity=self.camera.identity,source_boot_id='boot-old',forward_name_build=self.build,inverse_name_build=None,
            program_builds=programs,journal=[dict(event='native_intent',result='a7c2.names.result',mode=1)])
        self.save()
        self.temps={'lut-names-staged.so':path.read_bytes(),'a7c2.names.request':struct.pack('<8sII',b'A7NAM001',1,0),'a7c2.names.result':self.raw}
        self.camera.temp_read=lambda name,missing=False:self.temps.get(name)
        self.camera.temp_remove=lambda name:self.temps.pop(name)

    def save(self):(self.failed/'direct.private.json').write_text(json.dumps(self.state),encoding='utf-8')
    def job(self):return SimDirect(self.root/'resume',factory=self.camera)

    def test_prepare_accounts_actual_report_without_any_program_or_recipe_write(self):
        before={p:p.read_bytes() for p in self.failed.rglob('*') if p.is_file()}
        snapshots=copy.deepcopy((self.camera.ram,self.camera.saved))
        job=self.job();result=job.prepare_names_reload(self.failed,power_confirmed=True)
        self.assertEqual(result['phase'],namespause.WAIT)
        self.assertEqual(self.camera.mode,'0\n')
        self.assertFalse(any(kind in ('program','names') for kind,mode in self.camera.native_calls))
        self.assertEqual((self.camera.ram,self.camera.saved),snapshots)
        self.assertEqual(self.temps,{})
        self.assertEqual(before,{p:p.read_bytes() for p in self.failed.rglob('*') if p.is_file()})
        self.assertEqual(job.verify_names_reload()['phase'],namespause.WAIT)
        self.camera.boot='boot-new';self.camera.usr_mount_readonly=True
        self.assertEqual(job.verify_names_reload()['phase'],'RESOURCE_RELOAD_VERIFIED')

    def test_only_the_paused_path_says_reading_and_writing_have_ended(self):
        # Ready, the worker writes the programs next in the same job (worker.py: direct_resume_looks), so
        # that line would tell the user to pull the battery before the riskiest write. Paused, the job ends.
        import contextlib, io
        for readonly, ended in ((True, False), (False, True)):
            with self.subTest(readonly=readonly):
                self.camera.usr_mount_readonly = readonly
                self.temps.update({'lut-names-staged.so': Path(self.build['path']).read_bytes(),
                                   'a7c2.names.request': struct.pack('<8sII', b'A7NAM001', 1, 0), 'a7c2.names.result': self.raw})
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    SimDirect(self.root / ('said-' + str(readonly)), factory=self.camera).prepare_names_reload(
                        self.failed, power_confirmed=True)
                self.assertEqual('所有读写已结束' in output.getvalue(), ended)
                if readonly:
                    self.assertIn('无需断电重开。接下来安装程序，请保持 USB 连接。', output.getvalue())

    def test_already_readonly_does_not_force_an_extra_cold_boot(self):
        self.camera.usr_mount_readonly=True
        job=self.job();result=job.prepare_names_reload(self.failed,power_confirmed=True)
        self.assertEqual(result['phase'],'RESOURCE_RELOAD_VERIFIED')
        self.assertTrue(result['resource_reload_not_needed'])
        self.assertFalse(any(kind=='wbi' for kind,mode in self.camera.native_calls))

    def test_changed_name_or_program_or_foreign_temp_does_not_prepare_reload(self):
        for failure in ('name','program','temp'):
            files=dict(self.camera.files);temps=dict(self.temps)
            if failure=='name':self.camera.files['/usr/share/app/'+nameworker.filenames()[0]]+=b'bad!'
            elif failure=='program':self.camera.files['/usr/lib/appFw.so']=b'\1'+self.current['appFw.so'][1:]
            else:self.temps['libJit.so']=b'unknown'
            job=SimDirect(self.root/('stop-'+failure),factory=self.camera)
            with self.assertRaises(ValueError):job.prepare_names_reload(self.failed,power_confirmed=True)
            self.assertFalse(self.camera.native_calls)
            self.camera.files=files;self.temps.clear();self.temps.update(temps)

    def test_read_error_after_completed_cleaned_names_continues_without_name_write(self):
        # Field case: names committed and cleaned up, then "Wrong senser
        # sequence" before the first program stage. Clean and busy reports.
        clean=nameworker.REPORT.pack(b'A7NMR001',1,1,9,68,0,0,0,0,0,0,517,68,0,68,0,0,0,bytes(32))
        done=[dict(event='native_result_verified',stage='lut-names-staged.so',mode=1,result={}),
              dict(event='native_cleanup_verified',stage='lut-names-staged.so',mode=1)]
        for raw in (clean,self.raw):
            with self.subTest(busy=raw is self.raw):
                (self.failed/'evidence/failed-names-forward-1.bin').write_bytes(raw)
                self.state['journal']=[dict(event='native_intent',result='a7c2.names.result',mode=1),*done]
                self.save();self.temps.clear()
                self.assertEqual(namespause.source(self.failed)[2],raw)
                job=SimDirect(self.root/('after-'+str(len(self.camera.native_calls))+str(raw is self.raw)),factory=self.camera)
                job.prepare_names_reload(self.failed,power_confirmed=True)
                self.assertFalse(any(kind in ('program','names') for kind,mode in self.camera.native_calls))
                # Anything that ran after the names is not this checkpoint.
                self.state['journal'].append(dict(event='native_intent',result='a7c2.wbi.result',mode=0))
                self.save()
                with self.assertRaisesRegex(ValueError,'Unknown operation'):namespause.source(self.failed)
        self.build['stream_install']=False;self.state['forward_name_build']=self.build
        self.state['journal']=[dict(event='native_intent',result='a7c2.names.result',mode=1),*done];self.save()
        (self.failed/'evidence/failed-names-forward-1.bin').write_bytes(clean)
        with self.assertRaisesRegex(ValueError,'not fully accounted'):namespause.source(self.failed)

    def test_only_complete_clean_stream_name_busy_is_accepted(self):
        self.assertTrue(nameworker.validate(self.raw,1,self.build,allow_completed_busy=True)['readonly_deferred_busy'])
        with self.assertRaises(ValueError):nameworker.validate(self.raw,1,self.build)
        for index,value in ((3,5),(6,-5),(7,-16),(9,-5),(12,67),(14,67),(15,1)):
            v=list(nameworker.REPORT.unpack(self.raw));v[index]=value
            with self.assertRaises(ValueError):nameworker.validate(nameworker.REPORT.pack(*v),1,self.build,allow_completed_busy=True)

    @contextlib.contextmanager
    def look_write(self,job):
        """What a look write of 'CC' into Custom 1 needs on the simulated camera: its plan (the stand-in
        programs' change and the renamed name files), the worker compiler, and a session opener that
        binds the body only when asked to. The names are written as a busy, complete stream install."""
        renamed={n:self.camera.files['/usr/share/app/'+n] for n in nameworker.filenames()}
        def plan(current,*args,**kwargs):
            target=dict(current);target['appFw.so']=self.target['appFw.so']
            for n in nameworker.filenames():target['resources/'+n]=renamed[n]
            return target,[{},{}],({1:'CC'},resources.LABEL_IDS)
        def prepare(sources,*args,**kwargs):
            # The names are already as planned when a continuation reads them back.
            return dict(renamed),({'unchanged':True,'AP':None} if sources==renamed else self.build)
        def forward(cam,build,mode):
            self.forward_calls.append(mode)
            if mode==1:
                for n in nameworker.filenames():cam.files['/usr/share/app/'+n]=renamed[n]
                job.raw('names-forward-1.bin',self.raw)
                return dict(readonly_deferred_busy=True)
        original_call=Camera.__call__
        with patch.object(Camera,'__call__',lambda c,expected=None:c if expected is None else original_call(c,expected)), \
             patch.object(direct,'plan',side_effect=plan),patch.object(checkpointworker,'compile_worker',side_effect=fake_compile), \
             patch.object(nameworker,'prepare',side_effect=prepare),patch.object(job,'forward_names',side_effect=forward):
            yield

    def paused_look_write(self,folder='fresh'):
        """A fresh camera and the look write that paused on it after the names: (camera, job)."""
        camera=Camera(self.current);camera.usr_mount_readonly=False;camera.boot='boot-old'
        job=SimDirect(self.root/folder,factory=camera)
        with self.look_write(job):
            result=job.run_direct('look_import',version='2.01',power_confirmed=True,slot=1,look_path=self.failed/'reference.a7look')
        self.assertEqual(result['phase'],namespause.WAIT)
        return camera,job

    def test_fresh_writer_pauses_after_full_name_readback_before_programs(self):
        camera,_=self.paused_look_write()
        self.assertFalse(any(kind=='program' and mode==1 for kind,mode in camera.native_calls))
        self.assertEqual(camera.files['/usr/lib/appFw.so'],self.current['appFw.so'])
        self.assertEqual(camera.saves,[]);self.assertEqual(camera.mode,'0\n')

    # Continuing after the cold restart, in one service connection ------------------------------------

    def camera_state(self,camera):
        """Everything the simulated camera holds: files (programs, names, temporaries), settings in RAM and
        saved, and its setting saves."""
        return copy.deepcopy((camera.files,camera.ram,camera.saved,camera.saves))

    def continue_look_write(self,camera,paused,folder='continue'):
        """Continue `paused` as the worker does, in a fresh writer whose one session runs the paused job's
        checks before it writes. (outcome: the result or the ValueError, sessions opened, the camera and the
        name writes as they were when the readiness check ran, or None when it never ran)."""
        job=SimDirect(self.root/folder,factory=camera)
        sessions,at_check=[],[]
        ready=paused.names_reload_ready
        def check(runtime):
            at_check.append((self.camera_state(camera),list(self.forward_calls)))
            return ready(runtime)
        camera.native_calls.clear();self.forward_calls.clear()
        with self.look_write(job),patch.object(Camera,'__enter__',lambda c:(sessions.append(c),c)[1]), \
             patch.object(paused,'names_reload_ready',side_effect=check):
            try:
                outcome=job.run_direct('look_import',version='2.01',power_confirmed=True,slot=1,
                                       look_path=str(paused.root/'reference.a7look'),paused=paused)
            except ValueError as exc:
                outcome=exc
        return job,outcome,sessions,(at_check[0] if at_check else None)

    def paused_record(self,paused):
        return paused.state_path.read_bytes()

    def test_after_the_cold_restart_one_connection_checks_the_names_and_writes_the_programs(self):
        camera,paused=self.paused_look_write()
        camera.boot='boot-new';camera.usr_mount_readonly=True
        before,record=self.camera_state(camera),self.paused_record(paused)
        job,result,sessions,at_check=self.continue_look_write(camera,paused)
        self.assertEqual(result['phase'],'AWAITING_RELOAD')
        self.assertEqual(len(sessions),1)
        self.assertEqual(camera.files['/usr/lib/appFw.so'],self.target['appFw.so'])
        self.assertEqual(at_check,(before,[]))  # nothing on the camera had changed when the check ran
        self.assertNotIn(1,self.forward_calls)  # no name write: they were already written (forward_names skips them)
        self.assertEqual(job.state['names_resume_from'],str(paused.root))
        self.assertIn('names_reload_verified',[event['event'] for event in job.state['journal']])
        self.assertEqual(self.paused_record(paused),record)  # the paused job's record is evidence; left as it was

    def test_without_the_cold_restart_nothing_is_written_and_the_paused_job_stays(self):
        for boot,readonly in (('boot-old',True),('boot-new',False),('',True)):
            with self.subTest(boot=boot,readonly=readonly):
                camera,paused=self.paused_look_write('paused-%s-%s'%(boot,readonly))
                camera.boot,camera.usr_mount_readonly=boot,readonly
                before,record=self.camera_state(camera),self.paused_record(paused)
                job,outcome,sessions,_=self.continue_look_write(camera,paused,'continue-%s-%s'%(boot,readonly))
                self.assertIsInstance(outcome,direct.ResourceReloadPending)
                self.assertEqual(len(sessions),1)
                self.assertEqual(self.camera_state(camera),before)
                self.assertEqual(self.paused_record(paused),record)
                self.assertEqual(job.state['names_resume_from'],str(paused.root))

    def test_changed_names_stop_the_continuation_before_any_write(self):
        name='/usr/share/app/'+nameworker.filenames()[0]
        for change,reason in (('appended',r'inverse size'),('same length','Complete name readback differs')):
            with self.subTest(change=change):
                camera,paused=self.paused_look_write('paused-'+change)
                camera.boot='boot-new';camera.usr_mount_readonly=True
                data=camera.files[name]
                camera.files[name]=data+b'bad!' if change=='appended' else data[:-1]+bytes([data[-1]^1])
                before,record=self.camera_state(camera),self.paused_record(paused)
                job,outcome,sessions,at_check=self.continue_look_write(camera,paused,'continue-'+change)
                # The paused job no longer holds: it can never continue, so the page offers a fresh retry.
                self.assertIsInstance(outcome,direct.PausedJobChanged)
                self.assertRegex(str(outcome),reason)
                self.assertIsNone(at_check)  # refused before the readiness check
                self.assertEqual(camera.native_calls,[])  # and before the plan's probe: right after the camera was read
                self.assertEqual(job.state['failed_during'],'READING')
                self.assertEqual(self.camera_state(camera),before)
                self.assertEqual(self.paused_record(paused),record)

    def test_another_body_is_refused_when_the_session_opens(self):
        camera,paused=self.paused_look_write()
        camera.boot='boot-new';camera.usr_mount_readonly=True
        camera.identity=dict(camera.identity,serial_sha256='another-body')
        before,record=self.camera_state(camera),self.paused_record(paused)
        job,outcome,sessions,at_check=self.continue_look_write(camera,paused)
        # The fake binds in its opener; the real session refuses in __enter__ (BodyMismatch), also a ValueError.
        self.assertIsInstance(outcome,ValueError);self.assertNotIsInstance(outcome,direct.PausedJobChanged)
        self.assertEqual(sessions,[]);self.assertIsNone(at_check)
        self.assertEqual(camera.native_calls,[]);self.assertEqual(job.state['failed_during'],'READING')
        self.assertEqual(self.camera_state(camera),before)
        self.assertEqual(self.paused_record(paused),record)

    def test_only_a_look_write_continues_a_names_paused_job(self):
        camera,paused=self.paused_look_write()
        for mode in ('fl23_enable','factory_reset','sound_enable'):
            with self.subTest(mode=mode):
                job=SimDirect(self.root/('other-'+mode),factory=camera)
                with self.assertRaisesRegex(ValueError,'names-paused'):
                    job.run_direct(mode,version='2.01',power_confirmed=True,paused=paused)
                self.assertFalse(job.root.exists())

    def test_a_recovered_names_job_installs_its_programs_checked_in_the_writers_session(self):
        # The rarer path: names stopped busy (NEEDS_REVIEW), prepare_names_reload found /usr read-only and
        # verified it; its program-install child checks the recovery job again and records where it came from.
        self.camera.usr_mount_readonly=True;self.camera.boot='boot-new'
        recovery=self.job()
        self.assertEqual(recovery.prepare_names_reload(self.failed,power_confirmed=True)['phase'],'RESOURCE_RELOAD_VERIFIED')
        record=self.paused_record(recovery)
        job=SimDirect(recovery.root/'program-install',factory=self.camera)
        with self.look_write(job):
            result=job.run_direct('look_import',version='2.01',power_confirmed=True,slot=1,
                                  look_path=str(recovery.root/'reference.a7look'),paused=recovery)
        self.assertEqual(result['phase'],'AWAITING_RELOAD')
        self.assertEqual(self.camera.files['/usr/lib/appFw.so'],self.target['appFw.so'])
        self.assertEqual(job.state['names_resume_from'],str(recovery.root))
        self.assertEqual(self.paused_record(recovery),record)
