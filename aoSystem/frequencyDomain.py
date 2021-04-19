#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Apr 19 11:34:44 2021

@author: omartin
"""

# IMPORTING PYTHON LIBRAIRIES
import numpy as np
import aoSystem.fourier.FourierUtils as FourierUtils
from aoSystem.anisoplanatismModel import anisoplanatismStructureFunction

#%%
rad2mas = 3600 * 180 * 1000 / np.pi
rad2arc = rad2mas / 1000

class frequencyDomain():
    
    # WAVELENGTH
    @property
    def wvl(self):
        return self.__wvl
    @wvl.setter
    def wvl(self,val):
        self.__wvl = val
        self.samp  = val* rad2mas/(self.psInMas*self.ao.tel.D)
    @property
    def wvlCen(self):
        return self.__wvlCen
    @wvlCen.setter
    def wvlCen(self,val):
        self.__wvlCen = val
        self.sampCen  = val* rad2mas/(self.psInMas*self.ao.tel.D)
    @property
    def wvlRef(self):
        return self.__wvlRef
    @wvlRef.setter
    def wvlRef(self,val):
        self.__wvlRef = val
        self.sampRef  = val* rad2mas/(self.psInMas*self.ao.tel.D)    
    # SAMPLING
    @property
    def samp(self):
        return self.__samp
    @samp.setter
    def samp(self,val):
        self.k_      = np.ceil(2.0/val).astype('int') # works for oversampling
        self.__samp  = self.k_ * val     
    @property
    def sampCen(self):
        return self.__sampCen
    @sampCen.setter
    def sampCen(self,val):
        self.kCen_      = int(np.ceil(2.0/val))# works for oversampling
        self.__sampCen  = self.kCen_ * val  
    @property
    def sampRef(self):
        return self.__sampRef
    @sampRef.setter
    def sampRef(self,val):
        self.kRef_      = int(np.ceil(2.0/val)) # works for oversampling
        self.__sampRef  = self.kRef_ * val
        self.kxky_      = FourierUtils.freq_array(self.nPix*self.kRef_,self.__sampRef,self.ao.tel.D)
        self.k2_        = self.kxky_[0]**2 + self.kxky_[1]**2                   
        #piston filtering        
        self.pistonFilter_ = FourierUtils.pistonFilter(self.ao.tel.D,self.k2_)
        self.pistonFilter_[self.nPix*self.kRef_//2,self.nPix*self.kRef_//2] = 0
    
    # CUT-OFF FREQUENCY
    @property
    def pitch(self):
        return self.__pitch    
    @pitch.setter
    def pitch(self,val):
        self.__pitch = val
        # redefining the ao-corrected area
        if np.all(self.kcExt !=None):
            self.kc_= self.kcExt
        else:
            #return 1/(2*max(self.pitchs_dm.min(),self.pitchs_wfs.min()))
            self.kc_ =  1/(2*val)
            #self.kc_= (val-1)/(2.0*self.ao.tel.D)
        
        kc2     = self.kc_**2
        if self.ao.dms.AoArea == 'circle':
            self.mskOut_   = (self.k2_ >= kc2)
            self.mskIn_    = (self.k2_ < kc2)
        else:
            self.mskOut_   = np.logical_or(abs(self.kxky_[0]) >= self.kc_, abs(self.kxky_[1]) >= self.kc_)
            self.mskIn_    = np.logical_and(abs(self.kxky_[0]) < self.kc_, abs(self.kxky_[1]) < self.kc_)
        self.psdKolmo_     = 0.0229 * self.mskOut_* ((1.0 /self.ao.atm.L0**2) + self.k2_) ** (-11.0/6.0)
        self.wfe_fit_norm  = np.sqrt(np.trapz(np.trapz(self.psdKolmo_,self.kxky_[1][0]),self.kxky_[1][0]))
    
    @property
    def kcInMas(self):
        """DM cut-of frequency"""
        radian2mas = 180*3600*1e3/np.pi
        return self.kc_*self.ao.atm.wvl*radian2mas
    
    @property
    def nTimes(self):
        """"""
        return min(2,int(np.ceil(self.nOtf/self.resAO/2)))
    
    
    def __init__(self,aoSys,kcExt=None,Shannon=False):
        
        # PARSING INPUTS TO GET THE SAMPLING VALUES
        self.ao     = aoSys
        
        # MANAGING THE PIXEL SCALE
        self.nWvl   = len(self.ao.src.wvl)
        if Shannon:
            self.shannon    = True
            self.psInMas    = self.ao.src.wvl/self.al.tel.D/2
        else:
            self.psInMas    = self.ao.cam.psInMas * np.ones(self.nWvl)
            self.shannon    = False
                
                
        self.kcExt  = kcExt
        self.nPix   = self.ao.cam.fovInPix
        self.wvl    = self.ao.src.wvl
        self.wvlCen = np.mean(self.ao.src.wvl)
        self.wvlRef = np.min(self.ao.src.wvl)
        self.pitch  = self.ao.dms.pitch
        self.nOtf   = self.nPix * self.kRef_
        
        # DEFINING THE DOMAIN OF SPATIAL FREQUENCIES
        self.PSDstep= np.min(self.psInMas/self.ao.src.wvl/rad2mas)
        self.resAO  = int(2*self.kc_/self.PSDstep)
        self.nOtf   = self.nPix * self.kRef_
        
        k2D         = np.mgrid[0:self.resAO, 0:self.resAO].astype(float)
        self.kx     = self.PSDstep*(k2D[0] - self.resAO//2)  +1e-10
        self.ky     = self.PSDstep*(k2D[1] - self.resAO//2) + 1e-10    
        self.kxy    = np.hypot(self.kx,self.ky)    
        
        # DEFINE THE PISTON FILTER FOR LOW-ORDER FREQUENCIES
        self.pistonFilterIn_ = FourierUtils.pistonFilter(self.ao.tel.D,self.kxy)
        
        # DEFINE THE FREQUENCY DOMAIN OVER THE FULL PSD DOMAIN
        k2D = np.mgrid[0:self.nOtf, 0:self.nOtf].astype(float)
        self.kxExt      = self.PSDstep*(k2D[0] - self.nOtf//2)
        self.kyExt      = self.PSDstep*(k2D[1] - self.nOtf//2)
        self.kExtxy     = np.hypot(self.kxExt,self.kyExt)  
            
        # DEFINING THE DOMAIN ANGULAR FREQUENCIES
        self.U_, self.V_, self.U2_, self.V2_, self.UV_=  FourierUtils.instantiateAngularFrequencies(self.nOtf,fact=2)
              
        # COMPUTING THE STATIC OTF IF A PHASE MAP IS GIVEN
        self.otfNCPA, _ = FourierUtils.getStaticOTF(self.ao.tel,self.nOtf,self.sampRef,self.wvlRef, apodizer=self.ao.tel.apodizer,opdMap_ext=self.ao.tel.opdMap_ext)
        self.otfDL,_    = FourierUtils.getStaticOTF(self.ao.tel,self.nOtf,self.sampRef,self.wvlRef, apodizer=self.ao.tel.apodizer)
        self.otfDL      = np.real(self.otfDL)
        
        # ANISOPLANATISM PHASE STRUCTURE FUNCTION
        if (self.ao.aoMode == 'NGS') or (self.ao.aoMode == 'LGS'):
            self.dphi_ani = self.anisoplanatismPhaseStructureFunction()
        else:
            self.isAniso = False
            self.dphi_ani = None
            
    def anisoplanatismPhaseStructureFunction(self):
        
        # compute th Cn2 profile in m^(-5/3)
        Cn2 = self.ao.atm.weights * self.ao.atm.r0**(-5/3)
        
        if self.ao.aoMode == 'NGS':
            # NGS case : angular-anisoplanatism only
            self.isAniso = True
            self.dani_ang = anisoplanatismStructureFunction(self.ao.tel,self.ao.atm,self.ao.src,self.ao.ngs,self.ao.ngs,self.nOtf,self.sampRef)
            return (self.dani_ang *Cn2[np.newaxis,:,np.newaxis,np.newaxis]).sum(axis=1)
        
        elif self.ao.aoMode == 'LGS':
            # LGS case : focal-angular  + anisokinetism
            self.isAniso = True
            self.dani_focang,self.dani_ang,self.dani_tt = anisoplanatismStructureFunction(self.ao.tel,self.ao.atm,self.ao.src,self.ao.lgs,self.ao.ngs,self.nOtf,self.sampRef,Hfilter=self.trs.mat.Hdm)
            return ( (self.dani_focang.T + self.dani_tt.T) *Cn2[np.newaxis,:,np.newaxis,np.newaxis]).sum(axis=1)
        
        else:
            self.isAniso = False
            return None