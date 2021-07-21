#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Aug 18 22:20:28 2018

@author: omartin
"""
#%% MANAGE PYTHON LIBRAIRIES
import numpy as np
import time
import sys as sys
import numpy.fft as fft

from aoSystem.aoSystem import aoSystem
from aoSystem.fourierModel import fourierModel
from aoSystem.anisoplanatismModel import anisoplanatismStructureFunction
import aoSystem.FourierUtils as FourierUtils
import psfr.psfrUtils as psfrUtils
from aoSystem.frequencyDomain import frequencyDomain as frequencyDomain

#%%
rad2mas = 3600 * 180 * 1000 / np.pi
rad2arc = rad2mas / 1000

class psfR:
    """
    """
    # INIT
    def __init__(self,trs,path_root='',nLayer=None,theta_ext=0):
        """
        """
        # READ PARFILE        
        tstart = time.time()
        
        # PARSING INPUTS
        if hasattr(trs,'path_ini') == False:
            print('ERROR : no .ini file attached with the telemetry object')
            return
        self.path_ini  = trs.path_ini
        self.trs       = trs
        self.theta_ext = theta_ext
        self.ao        = aoSystem(self.path_ini,path_root=path_root)
        self.tag       = 'PSF-R'
        if self.ao.error == False:
            
            # DEFINING THE FREQUENCY DOMAIN
            self.freq = frequencyDomain(self.ao)
            
            # DEFINING BOUNDS
            self.bounds = self.defineBounds()
        
            # INSTANTIATING THE FOURIER MODEL
            self.fao = fourierModel(self.path_ini,calcPSF=False,display=False)
            
            # INSTANTIATING THE FITTING PHASE STRUCTURE FUNCTION FOR r0=1m
            self.dphi_fit = self.fittingPhaseStructureFunction(1)
            
            # INSTANTIATING THE ALIASING PHASE STRUCTURE FUNCTION FOR r0=1m
            self.dphi_alias = self.aliasingPhaseStructureFunction(1)
            
            # INSTANTIATING THE AO RESIDUAL PHASE STRUCTURE FUNCTION 
            self.dphi_ao = self.aoResidualStructureFunction()
                
            # INSTANTIATING THE TT RESIDUAL PHASE STRUCTURE FUNCTION IN LGS MODE
            # IN NGS MODE, THE TIP-TILT CONTRIBUTION SHOULD BE ADDED TO THE RESIDUAL WAVEFRONT
            # TO ACCOUNT FOR THE CROSS-TERMS
            self.dphi_tt = self.tipTiltPhaseStructureFunction()

            # INSTANTIATING THE ANISOPLANATISM PHASE STRUCTURE FUNCTION IF ANY
            if (self.ao.lgs==None) or (self.ao.lgs.height == 0):
                self.dphi_ani = anisoplanatismStructureFunction(\
                self.ao.tel,self.ao.atm,self.ao.src,self.ao.ngs,self.ao.ngs,\
                self.freq.nOtf,self.freq.sampRef,self.ao.dms.nActu1D,Hfilter=1)#self.trs.mat.Hdm)        
            else:
                self.dani_focang, self.dani_ang, self.dani_tt = anisoplanatismStructureFunction(\
                self.ao.tel,self.ao.atm,self.ao.src,self.ao.lgs,self.ao.ngs,\
                self.freq.nOtf,self.freq.sampRef,self.ao.dms.nActu1D,Hfilter=1)#self.trs.mat.Hdm)  
                self.dphi_ani = self.dani_focang + self.dani_tt
            
            # COMPUTING THE DETECTOR PIXEL TRANSFER FUNCTION
            if self.trs.tel.name != 'simulation':
                self.otfPixel = self.pixelOpticalTransferFunction()
            else:
                self.otfPixel = 1.0
            
            # COMPUTING THE ERROR BREAKDOWN:
            self.get_error_breakdown()
            
        self.t_init = 1000*(time.time()  - tstart)
    
    def _repr__(self):
        return 'PSF-Reconstruction model'
   
    def defineBounds(self):
          #r0, gao, gtt, F , dx , dy , bg , stat
          _EPSILON = np.sqrt(sys.float_info.epsilon)
          
          # Bounds on r0
          bounds_down = list(np.ones(self.ao.atm.nL)*_EPSILON)
          bounds_up   = list(np.inf * np.ones(self.ao.atm.nL))            
          # optical gains 
          bounds_down += [0,0]
          bounds_up   += [np.inf,np.inf]         
          # Photometry
          bounds_down += list(np.zeros(self.ao.src.nSrc))
          bounds_up   += list(np.inf*np.ones(self.ao.src.nSrc))
          # Astrometry
          bounds_down += list(-self.freq.nPix//2 * np.ones(2*self.ao.src.nSrc))
          bounds_up   += list( self.freq.nPix//2 * np.ones(2*self.ao.src.nSrc))
          # Background
          bounds_down += [-np.inf]
          bounds_up   += [np.inf]
          # Static aberrations
          bounds_down += list(-self.freq.wvlRef/2*1e9 * np.ones(self.ao.tel.nModes))
          bounds_up   += list(self.freq.wvlRef/2 *1e9 * np.ones(self.ao.tel.nModes))
          return (bounds_down,bounds_up)
      
    def fittingPhaseStructureFunction(self,r0):
        return r0**(-5/3) * np.real(fft.fftshift(FourierUtils.cov2sf(FourierUtils.psd2cov(self.freq.psdKolmo_,2*self.freq.kc_/self.freq.resAO))))
    
    def aliasingPhaseStructureFunction(self,r0):
        # computing the aliasing PSD over the AO-corrected area
        self.psdAlias_ = self.fao.aliasingPSD()/self.fao.ao.atm.r0**(-5/3)
        
        # zero-padding the PSD
        self.psdAlias_ = FourierUtils.enlargeSupport(self.psdAlias_,self.freq.nOtf/self.freq.resAO)
       
        # computing the aliasing phase structure function
        dphi_alias = r0**(-5/3) * np.real(fft.fftshift(FourierUtils.cov2sf(FourierUtils.psd2cov(self.psdAlias_,2*self.freq.kc_/self.freq.resAO))))
        
        # interpolating the phase structure function if required
        if dphi_alias.shape[0] != self.freq.nOtf:
            dphi_alias = FourierUtils.interpolateSupport(dphi_alias,self.freq.nOtf,kind='spline')
        return dphi_alias
    
    def aoResidualStructureFunction(self,method='slopes-based',basis='Vii'):
        """
        """
        # computing the empirical covariance matrix of the AO-residual OPD in the DM actuators domain
        if method == 'slopes-based':
            du = self.trs.rec.res
        elif method == 'dm-based':
            du = np.diff(self.trs.dm.com,axis=0)/self.ao.rtc.holoop['gain']    
        self.Cao  =  np.matmul(du.T,du)/du.shape[0]
       
        # Unbiasing noise and accounting for the wave number
        Cao = (2*np.pi/self.freq.wvlRef)**2 * (self.Cao - self.trs.wfs.Cn_ao)
        
        # Computing the phase structure function
        _,dphi_ao = psfrUtils.modes2Otf(Cao,self.trs.mat.dmIF,self.ao.tel.pupil,self.freq.nOtf,basis=basis,samp=self.freq.sampRef/2)
        
        return dphi_ao
            
    def tipTiltPhaseStructureFunction(self):
        """
        """
        # computing the empirical covariance matrix of the residual tip-tilt in meter
        self.Ctt = np.matmul(self.trs.tipTilt.slopes.T,self.trs.tipTilt.slopes)/self.trs.tipTilt.nExp
        
        # computing the coefficients of the Gaussian Kernel in rad^2
        Guu = (2*np.pi/self.freq.wvlRef)**2 *(self.Ctt - self.trs.tipTilt.Cn_tt) 
        
        # rotating the axes
        ang = self.trs.tel.pupilAngle * np.pi/180
        Ur  = self.freq.U_*np.cos(ang) + self.freq.V_*np.sin(ang)
        Vr  =-self.freq.U_*np.sin(ang) + self.freq.V_*np.cos(ang)  
        
        # computing the Gaussian-Kernel
        dphi_tt = Guu[0,0]*Ur**2 + Guu[1,1]*Vr**2 + Guu[0,1]*Ur*Vr.T + Guu[1,0]*Vr*Ur.T
        
        return dphi_tt * (self.ao.tel.D/2)**2
    
    def pixelOpticalTransferFunction(self):
        """
        """
        #note : self.U_/V_ ranges ar -1 to 1
        otfPixel = np.sinc(self.freq.U_)* np.sinc(self.freq.V_)
        return otfPixel

    def TotalPhaseStructureFunction(self,r0,gho,gtt,Cn2=[]):
        # On-axis phase structure function
        SF   = gho*self.dphi_ao + gtt*self.dphi_tt + r0**(-5/3) * (self.dphi_fit + self.dphi_alias)
        # Anisoplanatism phase structure function
        if self.freq.isAniso and (len(Cn2) == self.freq.dani_ang.shape[1]):
            SF = SF[:,:,np.newaxis] + (self.dphi_ani * Cn2).sum(axis=2)
        else:
            SF = np.repeat(SF[:,:,np.newaxis],self.ao.src.nSrc,axis=2)
        return SF/(2*np.pi*1e-9/self.freq.wvlRef)**2
    
    def __call__(self,x0,nPix=None):
                
        # ----------------- GETTING THE PARAMETERS
        # Cn2 profile
        nL   = self.ao.atm.nL
        if nL > 1: # fit the Cn2 profile
            Cn2  = np.asarray(x0[0:nL])
            r0   = np.sum(Cn2)**(-3/5)
        else: #fit the r0
            Cn2= []
            r0 = x0[0]
            
        # PSD
        gho = x0[nL]
        gtt = x0[nL+1]
        
        # Astrometry/Photometry/Background
        x0_stellar = np.array(x0[nL+2:nL+4+3*self.ao.src.nSrc])
        if len(x0_stellar):
            F  = x0_stellar[0:self.ao.src.nSrc][:,np.newaxis] * np.array(self.ao.cam.transmittance)[np.newaxis,:]
            dx = x0_stellar[self.ao.src.nSrc:2*self.ao.src.nSrc][:,np.newaxis] + np.array(self.ao.cam.dispersion[0])[np.newaxis,:]
            dy = x0_stellar[2*self.ao.src.nSrc:3*self.ao.src.nSrc][:,np.newaxis] + np.array(self.ao.cam.dispersion[1])[np.newaxis,:]
            bkg= x0_stellar[3*self.ao.src.nSrc]
        else:
            F  = np.repeat(np.array(self.ao.cam.transmittance)[np.newaxis,:]* np.ones(self.freq.nWvl),self.ao.src.nSrc,axis=0)
            dx = np.repeat(np.array(self.ao.cam.dispersion[0])[np.newaxis,:]* np.ones(self.freq.nWvl),self.ao.src.nSrc,axis=0)
            dy = np.repeat(np.array(self.ao.cam.dispersion[1])[np.newaxis,:]* np.ones(self.freq.nWvl),self.ao.src.nSrc,axis=0)
            bkg= 0.0
            
        # Static aberrations
        if len(x0) > nL + 2 + 3*self.ao.src.nSrc + 1:
            x0_stat = list(x0[nL+3+3*self.ao.src.nSrc:])
        else:
            x0_stat = []   
         
        # ----------------- GETTING THE PHASE STRUCTURE FUNCTION    
        self.SF = self.TotalPhaseStructureFunction(r0,gho,gtt,Cn2=Cn2)
        
        # ----------------- COMPUTING THE PSF
        PSF, self.SR = FourierUtils.SF2PSF(self.SF,self.freq,self.ao,\
                        F=F,dx=dx,dy=dy,bkg=bkg,nPix=nPix,xStat=x0_stat,otfPixel=self.otfPixel)
        return PSF
    
    def get_error_breakdown(self,r0=None,gho=1,gtt=1):
        '''
        Computing the AO error breakdown from the variance of each individual covariance terms.
        INPUTS:
            - an instance of the psfr object
        OUTPUTS
        '''
        sr2fwe = lambda x: np.sqrt(-np.log(x))* self.trs.atm.wvl*1e9/2/np.pi
        otf_dl = self.freq.otfDL
        S      = otf_dl.sum()
        self.wfe = dict()
        
        #1. STATIC ABERRATIONS
        self.wfe['NCPA'] = np.std(self.ao.tel.opdMap_on[self.ao.tel.pupil.astype(bool)])
        
        #2. DM FITTING ERROR
        if not r0:
            r0 = self.trs.atm.r0
        otf_fit = np.exp(-0.5 * r0**(-5/3) * self.dphi_fit)
        sr_fit  = np.sum(otf_dl * otf_fit)/S
        self.wfe['FITTING'] = sr2fwe(sr_fit)
        
        #3. WFS ALIASING ERROR
        otf_alias = np.exp(-0.5 * r0**(-5/3) * self.dphi_alias)
        sr_alias  = np.sum(otf_dl * otf_alias)/S
        self.wfe['ALIASING'] = sr2fwe(sr_alias)
        
        #4. WFS NOISE ERROR
        # noise on high-order modes
        msk = self.trs.dm.validActuators.reshape(-1)
        self.wfe['HO NOISE'] = 1e9 * np.sqrt(self.trs.holoop.tf.pn * np.mean(self.trs.wfs.Cn_ao[msk,msk]))
        # noise on tip-tilt modes
        self.wfe['TT NOISE'] = 1e9 * np.sqrt(self.trs.ttloop.tf.pn * np.diag(self.trs.tipTilt.Cn_tt).sum())
        
        #5. AO BANDWIDTH ERROR
        C = self.Cao - self.trs.wfs.Cn_ao
        self.wfe['SERVO-LAG'] = 1e9*np.sqrt(np.mean(np.mean(C[msk,msk])))
        
        #6. RESIDUAL TIP-TILT
        self.wfe['TIP-TILT'] = np.sqrt(np.sum(np.diag(self.Ctt - self.trs.tipTilt.Cn_tt)))*1e9
        sr_pixel = np.sum(otf_dl * self.otfPixel)/S
        self.wfe['PIXEL TF'] = np.sqrt(-np.log(sr_pixel))* self.freq.wvlRef*1e9/2/np.pi
      
        #7. ANISOPLANATISM
        Cn2     = self.ao.atm.weights * self.ao.atm.r0**(-5/3) * (self.ao.atm.wvl/self.ao.src.wvl[0])**2
        dani    = (self.dphi_ani[0].transpose(1,2,0) * Cn2).sum(axis=2)
        otf_ani = np.exp(-0.5 * dani)
        sr_ani  = np.sum(otf_dl * otf_ani)/S
        self.wfe['TOTAL ANISOPLANATISM'] = sr2fwe(sr_ani)
            
        if self.trs.aoMode == 'LGS':
            # Angular
            dani    = (self.dani_ang[0].transpose(1,2,0) * Cn2).sum(axis=2)
            otf_ani = np.exp(-0.5 * dani)
            sr_ani  = np.sum(otf_dl * otf_ani)/S
            self.wfe['ANGULAR ANISOPLANATISM'] = sr2fwe(sr_ani)
            #tiptilt
            dani    = (self.dani_tt[0].transpose(1,2,0) * Cn2).sum(axis=2)
            otf_ani = np.exp(-0.5 * dani)
            sr_ani  = np.sum(otf_dl * otf_ani)/S
            self.wfe['ANISOKINETISM'] = sr2fwe(sr_ani)
            # focal
            dani    = (self.dani_focang[0].transpose(1,2,0) * Cn2).sum(axis=2)
            otf_ani = np.exp(-0.5 * dani)
            sr_ani  = np.sum(otf_dl * otf_ani)/S
            self.wfe['FOCAL ANISOPLANATISM'] = np.sqrt(sr2fwe(sr_ani) **2 - self.wfe['ANGULAR ANISOPLANATISM']**2)
            
        #8. TOTAL WFE
        self.wfe['TOTAL WFE'] =  np.sqrt(self.wfe['NCPA']**2 +  self.wfe['FITTING']**2
                + self.wfe['HO NOISE']**2 + self.wfe['TT NOISE']**2 + self.wfe['SERVO-LAG']**2
                + self.wfe['TIP-TILT']**2 + self.wfe['TOTAL ANISOPLANATISM']**2)
        
        self.wfe['TOTAL WFE WITH PIXEL'] = np.hypot(self.wfe['TOTAL WFE'],self.wfe['PIXEL TF']) 
        
        # TOTAL STREHL-RATIO
        self.wfe['REF WAVELENGTH'] = self.freq.wvlRef
        self.wfe['MARECHAL SR'] = 1e2*np.exp(-(self.wfe['TOTAL WFE'] * 2*np.pi*1e-9/self.freq.wvlRef)**2 )
        self.wfe['MARECHAL SR WITH PIXEL'] = 1e2*np.exp(-(self.wfe['TOTAL WFE WITH PIXEL'] * 2*np.pi*1e-9/self.freq.wvlRef)**2 )
        
        if hasattr(self,'SR'):
            self.wfe['PSF SR'] = self.SR[0]
        self.wfe['IMAGE-BASED SR'] = 1e2*FourierUtils.getStrehl(self.trs.cam.image,self.ao.tel.pupil,self.freq.sampRef,method='max')
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        