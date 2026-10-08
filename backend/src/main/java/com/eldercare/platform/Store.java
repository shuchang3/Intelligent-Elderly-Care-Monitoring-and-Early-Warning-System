package com.eldercare.platform;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.core.type.TypeReference;
import org.springframework.stereotype.Component;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import java.sql.*;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.util.*;

@Component
public class Store implements ApplicationRunner {
    final JdbcTemplate db;
    final ObjectMapper json=new ObjectMapper();
    @Value("${app.node-code:NODE001}") String initialNode="NODE001";
    private final boolean initialize;
    private final String adminPassword,staffPassword;
    Store(JdbcTemplate db,@Value("${app.initialize}") boolean initialize,@Value("${app.admin-password}") String admin,@Value("${app.staff-password}") String staff){this.db=db;this.initialize=initialize;adminPassword=admin;staffPassword=staff;}
    public void run(ApplicationArguments args) {
        if(!initialize)return;
        Api.require(adminPassword.length()>=6&&staffPassword.length()>=6,"初始化密码至少6位");
        try {db.queryForObject("SELECT version FROM schema_version WHERE version=1",Integer.class);return;}catch(org.springframework.dao.DataAccessException e){
            try {db.queryForObject("SELECT COUNT(*) FROM sys_user",Long.class);throw new Api(409,"目标库不是空库，拒绝覆盖；请使用新的 elder_care_dev 数据库");}
            catch(org.springframework.jdbc.BadSqlGrammarException empty) { /* empty development database */ }
        }
        new ResourceDatabasePopulator(new ClassPathResource("schema.sql")).execute(Objects.requireNonNull(db.getDataSource()));
        var encoder=new BCryptPasswordEncoder();
        db.update("INSERT INTO sys_user(username,password,real_name,role) VALUES(?,?,?,?)","admin",encoder.encode(adminPassword),"管理员","ADMIN");
        db.update("INSERT INTO sys_user(username,password,real_name,role) VALUES(?,?,?,?)","staff01",encoder.encode(staffPassword),"护理人员","STAFF");
        db.update("INSERT INTO camera(camera_code,camera_name,location,capture_source,node_code,config_json) VALUES(?,?,?,?,?,?)","CAM001","本机摄像头","本机测试区域","0",initialNode,encode(Map.of("fallEnabled",true,"emotionEnabled",true,"strangerEnabled",true,"dangerEnabled",true,"sadSeconds",30,"missingSeconds",5,"fallCooldownSeconds",10,"captureFps",30,"soundEnabled",false)));
        for(var e:Map.of("FALL","URGENT","STRANGER","WARNING","DANGER_ZONE","WARNING","EMOTION_ABNORMAL","CARE","GEOFENCE_EXIT","WARNING").entrySet())db.update("INSERT INTO alert_rule VALUES(?,?)",e.getKey(),e.getValue());
        db.update("INSERT INTO schema_version(version) VALUES(1)");
    }
    List<Map<String,Object>> rows(String sql,Object...args) {
        return db.query(sql,(rs,index)->{
            var row=new LinkedHashMap<String,Object>();var meta=rs.getMetaData();
            for(int i=1;i<=meta.getColumnCount();i++) {
                String name=camel(meta.getColumnLabel(i).toLowerCase(Locale.ROOT));Object v=rs.getObject(i);
                if(v instanceof Timestamp t)v=t.toLocalDateTime().format(DateTimeFormatter.ISO_LOCAL_DATE_TIME);
                else if(v instanceof LocalDateTime t)v=t.format(DateTimeFormatter.ISO_LOCAL_DATE_TIME);
                else if(v instanceof Long)v=v.toString();
                row.put(name,v);
            }return row;
        },args);
    }
    Map<String,Object> one(String sql,Object...args){var r=rows(sql,args);if(r.isEmpty())throw new Api(404,"记录不存在");return r.getFirst();}
    long insert(String sql,Object...args){KeyHolder key=new GeneratedKeyHolder();db.update(c->{var p=c.prepareStatement(sql,new String[]{"id"});for(int i=0;i<args.length;i++)p.setObject(i+1,args[i]);return p;},key);return Objects.requireNonNull(key.getKey()).longValue();}
    String encode(Object v){try{return json.writeValueAsString(v);}catch(Exception e){throw new Api(400,"JSON数据无效");}}
    Map<String,Object> object(String value){try{return json.readValue(value,new TypeReference<Map<String,Object>>(){});}catch(Exception e){throw new Api(400,"JSON对象无效");}}
    List<Object> array(String value){try{return json.readValue(value,new TypeReference<List<Object>>(){});}catch(Exception e){throw new Api(400,"JSON数组无效");}}
    void log(Auth.User user,String op,String description){db.update("INSERT INTO operation_log(user_id,operation,description) VALUES(?,?,?)",user.id(),op,description);}
    static String camel(String v){var s=new StringBuilder();boolean upper=false;for(char c:v.toCharArray()){if(c=='_'){upper=true;continue;}s.append(upper?Character.toUpperCase(c):c);upper=false;}return s.toString();}
}
