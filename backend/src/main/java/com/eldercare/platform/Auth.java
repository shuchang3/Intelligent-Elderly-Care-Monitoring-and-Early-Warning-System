package com.eldercare.platform;

import io.jsonwebtoken.*;
import io.jsonwebtoken.security.Keys;
import jakarta.servlet.http.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

@Component
public class Auth {
    public record User(long id,String username,String role,int version,long expires){}
    record Ticket(User user,long expires){}
    final Store store;
    final byte[] secret;
    final String aiKey,nodeCode;
    final ConcurrentHashMap<String,Ticket> tickets=new ConcurrentHashMap<>();
    final BCryptPasswordEncoder encoder=new BCryptPasswordEncoder();
    Auth(Store store,@Value("${app.jwt-secret}") String secret,@Value("${app.ai-key}") String aiKey,@Value("${app.node-code}") String nodeCode){
        Api.require(secret.length()>=32,"JWT_SECRET至少32字符");this.store=store;this.secret=secret.getBytes(StandardCharsets.UTF_8);this.aiKey=aiKey;this.nodeCode=nodeCode;
    }
    User user(HttpServletRequest req){
        String header=req.getHeader("Authorization");if(header==null||!header.startsWith("Bearer "))throw new Api(401,"请登录");
        try {
            var c=Jwts.parserBuilder().setSigningKey(Keys.hmacShaKeyFor(secret)).build().parseClaimsJws(header.substring(7)).getBody();
            var u=new User(Long.parseLong(c.getSubject()),c.get("username",String.class),c.get("role",String.class),((Number)c.get("version")).intValue(),c.getExpiration().toInstant().getEpochSecond());
            if(!valid(u))throw new Api(401,"登录已失效");return u;
        }catch(Api e){throw e;}catch(JwtException|IllegalArgumentException e){throw new Api(401,"登录已失效");}
    }
    boolean valid(User u){
        if(u.expires()<=Instant.now().getEpochSecond())return false;
        var rows=store.rows("SELECT role,status,token_version FROM sys_user WHERE id=?",u.id());
        if(rows.isEmpty())return false;var r=rows.getFirst();
        return "NORMAL".equals(r.get("status"))&&u.role().equals(r.get("role"))&&u.version()==((Number)r.get("tokenVersion")).intValue();
    }
    Map<String,Object> login(Map<String,Object> body){
        String name=Api.text(body,"username",80),password=Api.text(body,"password",200);
        var rows=store.rows("SELECT * FROM sys_user WHERE username=?",name);
        if(rows.isEmpty()||!encoder.matches(password,rows.getFirst().get("password").toString())||!"NORMAL".equals(rows.getFirst().get("status")))throw new Api(401,"账号、密码或账号状态无效");
        var r=rows.getFirst();long expires=Instant.now().plusSeconds(7200).getEpochSecond();
        String token=Jwts.builder().setSubject(r.get("id").toString()).claim("username",name).claim("role",r.get("role")).claim("version",r.get("tokenVersion")).setIssuedAt(new Date()).setExpiration(Date.from(Instant.ofEpochSecond(expires))).signWith(Keys.hmacShaKeyFor(secret),SignatureAlgorithm.HS256).compact();
        return Map.of("token",token,"expiresAt",expires,"user",publicUser(r));
    }
    Map<String,Object> me(User u){return publicUser(store.one("SELECT * FROM sys_user WHERE id=?",u.id()));}
    Map<String,Object> publicUser(Map<String,Object> r){return Map.of("id",r.get("id"),"username",r.get("username"),"realName",r.get("realName"),"role",r.get("role"));}
    void admin(User u){if(!u.role().equals("ADMIN"))throw new Api(403,"需要管理员权限");}
    void staff(User u){if(!Set.of("ADMIN","STAFF").contains(u.role()))throw new Api(403,"需要护理人员权限");}
    void ai(HttpServletRequest req){String key=req.getHeader("X-AI-Key");if(aiKey.length()<32||key==null||!MessageDigest.isEqual(aiKey.getBytes(StandardCharsets.UTF_8),key.getBytes(StandardCharsets.UTF_8)))throw new Api(401,"算法服务认证失败");}
    void cameraForAI(String code){var camera=store.one("SELECT * FROM camera WHERE camera_code=?",code);if(!nodeCode.equals(camera.get("nodeCode")))throw new Api(403,"摄像头不属于当前算法节点");}
    boolean canPerson(User u,Object code){return !u.role().equals("FAMILY")||(code!=null&&store.db.queryForObject("SELECT COUNT(*) FROM family_binding WHERE user_id=? AND person_code=?",Long.class,u.id(),code)>0);}
    void event(User u,Map<String,Object> event){if(!canPerson(u,event.get("personCode")))throw new Api(403,"无权访问此事件");}
    String ticket(User u){tickets.entrySet().removeIf(e->e.getValue().expires()<System.currentTimeMillis());String token=UUID.randomUUID().toString();tickets.put(token,new Ticket(u,System.currentTimeMillis()+30000));return token;}
    User consume(String token){if(token==null)return null;Ticket t=tickets.remove(token);return t!=null&&t.expires()>System.currentTimeMillis()&&valid(t.user())?t.user():null;}
}
