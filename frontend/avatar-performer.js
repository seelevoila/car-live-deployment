/* Local avatar presentation. Not included in the competition source package. */
(function(root){
  const profiles={natural:{motion:0.65,smile:0.12},warm:{motion:0.75,smile:0.35},lively:{motion:1.1,smile:0.48},calm:{motion:0.4,smile:0.08}};
  class Performer {
    constructor(){this.energy=0;this.lastTime=0;this.nextBlink=2.7;this.blinkAt=-10;this.lastPulse=-10;this.pulseAt=-10;}
    update(core,time,mouth,{style='warm',enabled=true,paused=false}={}){
      const profile=profiles[style]||profiles.warm;
      const ids=core._model?.parameters?.ids;
      const set=(id,value)=>{if(!ids||ids.includes(id))core.setParameterValueById(id,value);};
      const dt=Math.min(.1,Math.max(0,time-this.lastTime));this.lastTime=time;
      this.energy+=(mouth-this.energy)*(1-Math.exp(-dt/.22));
      if(mouth>.26&&this.energy<.23&&time-this.lastPulse>.8){this.pulseAt=time;this.lastPulse=time;}
      if(time>this.nextBlink){this.blinkAt=time;this.nextBlink=time+3.4+Math.sin(time*1.7)*.8;}
      const blinkPhase=(time-this.blinkAt)/.18;
      const blink=blinkPhase>=0&&blinkPhase<1?Math.sin(blinkPhase*Math.PI):0;
      const strength=enabled&&!paused?profile.motion:0;
      const nodAge=time-this.pulseAt;
      const nod=nodAge>=0&&nodAge<.75?Math.sin(nodAge/.75*Math.PI)*Math.exp(-nodAge*2):0;
      // Mouth uses the real sound timeline; these low-frequency movements
      // only animate posture, gaze and expressions.
      set('ParamAngleX',strength*(Math.sin(time*.63)*6+this.energy*2));
      set('ParamAngleY',strength*(Math.sin(time*.81)*1.2-nod*5));
      set('ParamAngleZ',strength*Math.sin(time*.47)*2.5);
      set('ParamBodyAngleX',strength*Math.sin(time*.43)*2);
      set('ParamBodyAngleY',strength*(this.energy*1.8));
      set('ParamBodyAngleZ',strength*Math.sin(time*.47)*.65);
      set('ParamBreath',.5+.25*Math.sin(time*1.5));
      set('ParamEyeBallX',strength*Math.sin(time*.27)*.13);
      set('ParamEyeBallY',strength*Math.sin(time*.31)*.08);
      set('ParamEyeLOpen',1-blink);set('ParamEyeROpen',1-blink);
      set('ParamEyeLSmile',enabled?profile.smile*(.4+this.energy):0);
      set('ParamEyeRSmile',enabled?profile.smile*(.4+this.energy):0);
      set('ParamBrowLAngle',enabled?this.energy*.24:0);set('ParamBrowRAngle',enabled?this.energy*.24:0);
    }
  }
  root.AvatarPerformer={Performer};
})(globalThis);
