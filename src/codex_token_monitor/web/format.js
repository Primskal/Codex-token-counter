(function(global){
  function formatTokens(value){
    const numeric=Number(value);
    if(!Number.isFinite(numeric))return '0';
    const sign=numeric<0?'-':'';
    const absolute=Math.abs(numeric);
    const units=[['B',1e9],['M',1e6],['K',1e3]];
    let unitIndex=units.findIndex(([,divisor])=>absolute>=divisor);
    if(unitIndex>=0){
      let [suffix,divisor]=units[unitIndex];
      let rounded=Math.round((absolute/divisor+Number.EPSILON)*10)/10;
      if(rounded>=1000&&unitIndex>0){
        [suffix,divisor]=units[unitIndex-1];
        rounded=Math.round((absolute/divisor+Number.EPSILON)*10)/10;
      }
      return `${sign}${rounded.toFixed(1)}${suffix}`;
    }
    return `${sign}${Math.round(absolute)}`;
  }
  const api={formatTokens};
  global.CodexTokenMonitorFormat=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
