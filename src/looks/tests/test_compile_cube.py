"""CUBE input contracts: explicit ST domain or an explicit color bridge."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import numpy as np
from looktool import compilelook,lookfile,photoformat,measuredmodel
from looktool.compilelook import cube_targets


class CubeCompileTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def cube(self,name,transform):
        path=self.root/name
        rows=[transform(np.array([r,g,b],dtype=float)) for b in (0,1) for g in (0,1) for r in (0,1)]
        path.write_text('LUT_3D_SIZE 2\n'+'\n'.join(' '.join(map(str,row)) for row in rows)+'\n')
        return path

    def test_ST_input_applies_cube_in_the_declared_domain(self):
        path=self.cube('look.cube',lambda rgb:rgb*np.array([.8,.9,1.]))
        source=np.array([[.2,.4,.6],[.7,.1,.3]])
        target,report=cube_targets(source,path,'sony-st-srgb')
        np.testing.assert_allclose(target,source*[.8,.9,1.])
        self.assertFalse(report['Lightroom_reference_used'])
        self.assertFalse(report['automatic_Adobe_profile_generated'])

    def test_log_or_other_input_is_not_assumed_to_be_ST(self):
        path=self.cube('identity.cube',lambda rgb:rgb)
        for space,bridge in [(None,None),('f-log',None),('sony-st-srgb',path)]:
            with self.assertRaisesRegex(ValueError,'explicit bridge'):
                cube_targets(np.array([[.1,.2,.3]]),path,space,bridge)

    def test_explicit_bridge_is_applied_before_the_look(self):
        bridge=self.cube('bridge.cube',lambda rgb:rgb*.5)
        look=self.cube('look.cube',lambda rgb:rgb+np.array([.1,.0,.0]))
        result,report=cube_targets(np.array([[.2,.4,.6]]),look,'declared-video-space',bridge)
        np.testing.assert_allclose(result,[[.2,.2,.3]])
        self.assertTrue(report['bridge_used'])

    def test_unrepresentable_output_clipping_is_disclosed(self):
        look=self.cube('wide.cube',lambda rgb:rgb*2)
        result,report=cube_targets(np.array([[.8,.2,.9]]),look,'sony-st-srgb')
        np.testing.assert_allclose(result,[[1,.4,1]])
        self.assertEqual(report['clipped_output_components'],2)

    def compile(self,source,output,*extra,fit=None):
        """Run the CUBE compiler on a synthetic camera model; fit stands in for the slow optimiser."""
        from test_photoformat import curve
        calibration=self.root/'model.npz';calibration.write_bytes(b'fixture')
        bank=photoformat.PhotoBank(curve(),curve(),bytes(576),bytes(64))
        model=SimpleNamespace(metadata={'physical_scope':'Synthetic fixture'},
            arrays={'baseline_bank':np.frombuffer(bank.pack(),dtype=np.uint8)},
            virtual_samples=lambda count:(np.array([[.2,.3,.4]]),np.array([[.2,.3,.4]])))
        def fitted(*args,**kwargs):
            if fit:fit()
            return np.zeros((405,3)),dict(native_controls=[0]*17,final_optimizer=dict(optimizer_converged=True))
        with patch.object(measuredmodel,'Response',return_value=model),patch.object(compilelook,'fit',side_effect=fitted):
            code=compilelook.main([str(source),'--input-space','sony-st-srgb',*extra,'--name','Fixture',
                '--output',str(output),'--calibration',str(calibration),'--config',str(self.root/'none.json'),
                '--work',str(output.with_suffix('.work'))])
        self.assertEqual(code,0)
        return lookfile.read(output)

    def test_long_fit_uses_the_frozen_paired_DCP_after_original_changes(self):
        from test_rawprofiles import profile
        from looktool.rawidentity import source_bytes
        source=self.cube('source.cube',lambda rgb:rgb)
        paired=self.root/'source.dcp';original=profile('Original');paired.write_bytes(original)
        document=self.compile(source,self.root/'compiled.a7look','--raw-dcp',str(paired),
                              fit=lambda:paired.write_bytes(profile('Changed while fitting')))
        self.assertEqual(source_bytes(document['raw_profile']),original)
        self.assertNotEqual(paired.read_bytes(),original)

    def test_a_CUBE_source_is_attributed_as_a_CUBE(self):
        # A paired DCP only adds raw support; the look itself still comes from the CUBE.
        from test_rawprofiles import profile
        source=self.cube('source.cube',lambda rgb:rgb)
        paired=self.root/'paired.dcp';paired.write_bytes(profile('Paired'))
        for name,extra in (('plain',[]),('paired',['--raw-dcp',str(paired)])):
            document=self.compile(source,self.root/(name+'.a7look'),*extra)
            self.assertEqual(document['attribution'],'Owner-provided CUBE; original rights apply')

if __name__=='__main__':unittest.main()
