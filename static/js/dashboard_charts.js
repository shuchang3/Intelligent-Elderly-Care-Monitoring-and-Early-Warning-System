'use strict';
(() => {
  const chartInstances = {};
  const textColor = '#6b7280';
  const emptyOption = title => ({title:{text:'暂无真实数据',subtext:title,left:'center',top:'middle',textStyle:{fontSize:16,color:textColor},subtextStyle:{color:'#9ca3af'}},series:[]});
  function chart(id){const node=document.getElementById(id);if(!node||!window.echarts)return null;return chartInstances[id] ||= echarts.init(node);}
  function lastSevenDays(){const days=[];for(let offset=6;offset>=0;offset--){const date=new Date();date.setHours(0,0,0,0);date.setDate(date.getDate()-offset);days.push([date.getFullYear(),String(date.getMonth()+1).padStart(2,'0'),String(date.getDate()).padStart(2,'0')].join('-'));}return days;}
  window.renderDashboardCharts = () => {
    if(!window.echarts||!window.dashboardChartData)return;
    const {trend=[],types=[],emotion=[]}=window.dashboardChartData;
    const days=lastSevenDays(),trendMap=new Map(trend.map(row=>[String(row.day).slice(0,10),Number(row.count)]));
    const line=chart('lineChart');
    line?.setOption(trend.length?{tooltip:{trigger:'axis'},grid:{left:45,right:24,top:30,bottom:35},xAxis:{type:'category',data:days.map(v=>v.slice(5))},yAxis:{type:'value',minInterval:1},series:[{name:'告警数量',data:days.map(day=>trendMap.get(day)||0),type:'line',smooth:true,symbolSize:8,lineStyle:{color:'#1677ff',width:3},itemStyle:{color:'#1677ff'},areaStyle:{color:'rgba(22,119,255,.12)'}}]}:emptyOption('最近7天尚无告警记录'),true);
    const pie=chart('pieChart');
    pie?.setOption(types.length?{tooltip:{trigger:'item'},legend:{bottom:0},series:[{type:'pie',radius:['34%','62%'],center:['50%','45%'],label:{formatter:'{b}\n{c} 条'},data:types.map(row=>({name:typeNames[row.eventType]||row.eventType,value:Number(row.count)}))}]}:emptyOption('数据库中尚无告警类型统计'),true);
    const emotionChart=chart('emotionChart'),emotionDays=lastSevenDays(),emotionNames={neutral:'平静',happy:'开心',sad:'悲伤',angry:'生气',fear:'害怕',surprise:'惊讶',disgust:'厌恶'},groups=new Map();
    for(const row of emotion){const name=emotionNames[String(row.emotion).toLowerCase()]||row.emotion;if(!groups.has(name))groups.set(name,new Map());groups.get(name).set(String(row.day).slice(0,10),Number(row.samples));}
    emotionChart?.setOption(emotion.length?{tooltip:{trigger:'axis'},legend:{top:0},grid:{left:45,right:24,top:45,bottom:35},xAxis:{type:'category',data:emotionDays.map(v=>v.slice(5))},yAxis:{type:'value',name:'有效采样',minInterval:1},series:[...groups].map(([name,values])=>({name,type:'line',smooth:true,connectNulls:false,data:emotionDays.map(day=>values.has(day)?values.get(day):null)}))}:emptyOption('尚无有效情感采样，不能推断为情绪正常'),true);
  };
  window.renderDashboardCharts();
  window.addEventListener('resize',()=>Object.values(chartInstances).forEach(instance=>instance.resize()));
})();
