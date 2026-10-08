package com.eldercare.platform;

import java.util.*;

final class Validation {
    static void cameraConfig(Map<?,?> config) {
        var flags=Set.of("fallEnabled","strangerEnabled","emotionEnabled","dangerEnabled","soundEnabled");
        for(var e:config.entrySet()) {
            String key=e.getKey().toString();
            if(flags.contains(key))Api.require(e.getValue() instanceof Boolean,key+"必须是布尔值");
            else if(Set.of("sadSeconds","missingSeconds","fallCooldownSeconds").contains(key))seconds(e.getValue(),key);
            else if(key.equals("captureFps")){double fps=seconds(e.getValue(),key);Api.require(fps<=60,"captureFps不能超过60");}
            else throw new Api(400,"未知算法配置字段："+key);
        }
    }
    static double seconds(Object value,String key) {
        Api.require(value instanceof Number,key+"必须是数字");
        double v=((Number)value).doubleValue();
        Api.require(Double.isFinite(v)&&v>0&&v<=3600,key+"必须大于0且不超过3600秒");return v;
    }
    static double cross(double[] a,double[] b,double[] c){return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);}
    static boolean between(double[] a,double[] b,double[] p){return Math.abs(cross(a,b,p))<1e-9&&p[0]>=Math.min(a[0],b[0])-1e-9&&p[0]<=Math.max(a[0],b[0])+1e-9&&p[1]>=Math.min(a[1],b[1])-1e-9&&p[1]<=Math.max(a[1],b[1])+1e-9;}
    static void polygon(List<?> vertices) {
        var points=new ArrayList<double[]>();
        for(Object item:vertices){var p=(List<?>)item;points.add(new double[]{((Number)p.get(0)).doubleValue(),((Number)p.get(1)).doubleValue()});}
        double area=0;int n=points.size();
        for(int i=0;i<n;i++){
            var a=points.get(i);var b=points.get((i+1)%n);area+=a[0]*b[1]-b[0]*a[1];
            for(int j=i+1;j<n;j++){var p=points.get(j);Api.require(Math.hypot(a[0]-p[0],a[1]-p[1])>1e-6,"多边形不能有重复顶点");}
            for(int j=i+1;j<n;j++){
                if(j==(i+1)%n||(j+1)%n==i)continue;
                var c=points.get(j);var d=points.get((j+1)%n);
                boolean crossing=cross(a,b,c)*cross(a,b,d)<0&&cross(c,d,a)*cross(c,d,b)<0;
                Api.require(!crossing&&!between(a,b,c)&&!between(a,b,d)&&!between(c,d,a)&&!between(c,d,b),"区域边界不能自相交");
            }
        }
        Api.require(Math.abs(area)>.00001,"区域面积过小或顶点共线");
    }
}
