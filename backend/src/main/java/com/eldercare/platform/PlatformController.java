package com.eldercare.platform;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.http.*;
import org.springframework.core.io.FileSystemResource;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.dao.DuplicateKeyException;
import java.time.*;
import java.sql.Timestamp;
import java.util.*;
import java.nio.charset.StandardCharsets;
import java.net.http.*;
import java.util.concurrent.CompletableFuture;

@RestController
public class PlatformController {
    final Store s;final OptionalCache cache;final Auth auth;final EventsSocket socket;final Media media;final TransactionTemplate tx;
    final Set<String> types=Set.of("FALL","STRANGER","DANGER_ZONE","EMOTION_ABNORMAL","GEOFENCE_EXIT");
    PlatformController(Store s,OptionalCache cache,Auth auth,EventsSocket socket,Media media,PlatformTransactionManager manager){this.s=s;this.cache=cache;this.auth=auth;this.socket=socket;this.media=media;tx=new TransactionTemplate(manager);}
    @GetMapping("/health") Object health(){try{s.db.queryForObject("SELECT version FROM schema_version WHERE version=1",Integer.class);return Api.ok(Map.of("status","UP","database","UP","redis",cache.health(),"version","1.0.0"));}catch(Exception e){throw new Api(503,"数据库未连接或尚未初始化");}}
    @PostMapping("/api/v1/auth/login") Object login(@RequestBody Map<String,Object>b){return Api.ok(auth.login(b));}
    @GetMapping("/api/v1/auth/me") Object me(HttpServletRequest r){return Api.ok(auth.me(auth.user(r)));}
    @PostMapping("/api/v1/auth/logout") Object logout(HttpServletRequest r){var u=auth.user(r);s.db.update("UPDATE sys_user SET token_version=token_version+1 WHERE id=?",u.id());socket.expire();return Api.ok(null);}
    @PostMapping("/api/v1/auth/ws-ticket") Object ticket(HttpServletRequest r){return Api.ok(Map.of("ticket",auth.ticket(auth.user(r)),"expiresIn",30));}
    @PutMapping("/api/v1/auth/password") Object password(HttpServletRequest r,@RequestBody Map<String,Object>b){var u=auth.user(r);var row=s.one("SELECT password FROM sys_user WHERE id=?",u.id());String password=Api.text(b,"newPassword",200);Api.require(password.length()>=12,"密码至少12位");if(!auth.encoder.matches(Api.text(b,"oldPassword",200),row.get("password").toString()))throw new Api(400,"原密码错误");s.db.update("UPDATE sys_user SET password=?,token_version=token_version+1 WHERE id=?",auth.encoder.encode(password),u.id());socket.expire();return Api.ok(null);}
    @GetMapping("/api/v1/users") Object users(HttpServletRequest r){auth.admin(auth.user(r));return Api.ok(s.rows("SELECT id,username,real_name,role,status FROM sys_user ORDER BY id"));}
    @PostMapping("/api/v1/users") Object userCreate(HttpServletRequest r,@RequestBody Map<String,Object>b){var u=auth.user(r);auth.admin(u);String role=Api.text(b,"role",20),pass=Api.text(b,"password",200);Api.require(Set.of("ADMIN","STAFF","FAMILY").contains(role)&&pass.length()>=12,"角色无效或密码少于12位");long id=s.insert("INSERT INTO sys_user(username,password,real_name,role) VALUES(?,?,?,?)",Api.text(b,"username",80),auth.encoder.encode(pass),Api.text(b,"realName",100),role);s.log(u,"CREATE_USER",Long.toString(id));return Api.ok(Map.of("id",Long.toString(id)));}
    @PutMapping("/api/v1/users/{id}") Object userUpdate(HttpServletRequest r,@PathVariable long id,@RequestBody Map<String,Object>b){var u=auth.user(r);auth.admin(u);String role=Api.text(b,"role",20),status=Api.text(b,"status",20);Api.require(Set.of("ADMIN","STAFF","FAMILY").contains(role)&&Set.of("NORMAL","DISABLED").contains(status),"角色或状态无效");Api.require(id!=u.id()||role.equals("ADMIN")&&status.equals("NORMAL"),"不能禁用或降级当前管理员");s.db.update("UPDATE sys_user SET role=?,status=?,token_version=token_version+1 WHERE id=?",role,status,id);s.log(u,"UPDATE_USER",Long.toString(id));socket.expire();return Api.ok(null);}
    @GetMapping("/api/v1/family-bindings") Object bindings(HttpServletRequest r){auth.admin(auth.user(r));return Api.ok(s.rows("SELECT * FROM family_binding"));}
    @PostMapping("/api/v1/family-bindings") Object bind(HttpServletRequest r,@RequestBody Map<String,Object>b){var u=auth.user(r);auth.admin(u);String userId=Api.text(b,"userId",30),personCode=Api.text(b,"personCode",64);Api.require("FAMILY".equals(s.one("SELECT role FROM sys_user WHERE id=?",userId).get("role")),"账户不是家属");Api.require("ELDER".equals(s.one("SELECT person_type FROM person WHERE person_code=? AND enabled=TRUE",personCode).get("personType")),"只能绑定有效老人");try{s.db.update("INSERT INTO family_binding VALUES(?,?)",userId,personCode);}catch(DuplicateKeyException ignored){}s.log(u,"BIND_FAMILY",userId+":"+personCode);return Api.ok(null);}
    @DeleteMapping("/api/v1/family-bindings") Object unbind(HttpServletRequest r,@RequestParam long userId,@RequestParam String personCode){var u=auth.user(r);auth.admin(u);s.db.update("DELETE FROM family_binding WHERE user_id=? AND person_code=?",userId,personCode);s.log(u,"UNBIND_FAMILY",userId+":"+personCode);return Api.ok(null);}
    void afterCommit(Runnable work){TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization(){public void afterCommit(){try{work.run();}catch(Exception e){org.slf4j.LoggerFactory.getLogger(PlatformController.class).warn("Committed event notification failed; clients must resync",e);}}});}
    Map<String,Object> eventRow(long id){var row=s.one("SELECT * FROM event WHERE id=?",id);row.remove("contentHash");Object image=row.remove("imagePath");row.put("imageUrl",image==null?null:"/api/v1/events/"+id+"/snapshot");var videos=s.rows("SELECT state FROM event_video WHERE event_id=?",id);row.put("videoState",videos.isEmpty()?"PENDING":videos.getFirst().get("state"));return row;}
    @PostMapping(value="/api/v1/ai/events",consumes="multipart/form-data") Object report(HttpServletRequest req,@RequestParam Map<String,String>b,@RequestPart(required=false)MultipartFile snapshot)throws Exception{
        auth.ai(req);String number=Api.text(b,"eventNo",64);try{UUID.fromString(number);}catch(Exception e){throw new Api(400,"eventNo必须为UUID");}
        String type=Api.text(b,"eventType",32).toUpperCase(Locale.ROOT),camera=Api.text(b,"cameraCode",64);Api.require(types.contains(type),"事件类型无效");auth.cameraForAI(camera);
        var cameraRow=s.one("SELECT * FROM camera WHERE camera_code=? AND enabled=TRUE",camera);
        String person=Api.optional(b,"personCode",64),zone=Api.optional(b,"zoneCode",64),track=Api.optional(b,"trackId",64),description=Api.text(b,"description",1000),scoreType=Api.optional(b,"scoreType",64);
        if(person!=null)s.one("SELECT id FROM person WHERE person_code=? AND enabled=TRUE",person);
        if(type.equals("DANGER_ZONE")){Api.require(zone!=null,"危险区事件必须指定zoneCode");s.one("SELECT id FROM danger_zone WHERE zone_code=? AND camera_code=? AND enabled=TRUE",zone,camera);}
        String score=Api.optional(b,"confidence",30);Double confidence=score==null?null:Double.valueOf(score);Api.require(confidence==null||Double.isFinite(confidence)&&confidence>=0&&confidence<=1,"分数应在0到1之间");Api.require(confidence==null||scoreType!=null,"有分数时必须提供scoreType");
        var time=LocalDateTime.parse(Api.text(b,"eventTime",40));byte[] image=media.image(snapshot);
        var canonical=new TreeMap<String,Object>();canonical.putAll(b);canonical.remove("location");canonical.put("eventTime",time.toString());canonical.put("snapshot",image==null?null:Media.hash(image));String hash=Media.hash(s.encode(canonical).getBytes(StandardCharsets.UTF_8));
        var existing=s.rows("SELECT id,content_hash FROM event WHERE event_no=?",number);if(!existing.isEmpty())return duplicate(existing.getFirst(),hash);
        String filename=media.save(image,".jpg");
        try {
            long id=tx.execute(status->{
                String level=s.one("SELECT event_level FROM alert_rule WHERE event_type=?",type).get("eventLevel").toString();
                long key=s.insert("INSERT INTO event(event_no,event_type,camera_code,person_code,zone_code,track_id,event_time,description,confidence,score_type,location,image_path,content_hash,event_level) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",number,type,camera,person,zone,track,Timestamp.valueOf(time),description,confidence,scoreType,cameraRow.get("location"),filename,hash,level);
                s.db.update("INSERT INTO event_video(event_id,state) VALUES(?,?)",key,"PENDING");
                s.db.update("INSERT INTO notification_job(event_id,subscription_id) SELECT ?,p.id FROM push_subscription p JOIN sys_user u ON p.user_id=u.id WHERE u.status='NORMAL' AND (u.role IN ('ADMIN','STAFF') OR EXISTS(SELECT 1 FROM family_binding f WHERE f.user_id=u.id AND f.person_code=?))",key,person);
                afterCommit(()->{cache.invalidate();socket.send("EVENT_CREATED",eventRow(key));});return key;
            });return Api.ok(eventRow(id));
        }catch(DuplicateKeyException duplicate){media.delete(filename);return duplicate(s.one("SELECT id,content_hash FROM event WHERE event_no=?",number),hash);}catch(Exception e){media.delete(filename);throw e;}
    }
    Object duplicate(Map<String,Object> old,String hash){if(!hash.equals(old.get("contentHash")))throw new Api(409,"eventNo已用于不同内容");return Api.ok(eventRow(Long.parseLong(old.get("id").toString())));}
    String scope(Auth.User u,List<Object> args,String prefix){if(!u.role().equals("FAMILY"))return "";args.add(u.id());return " AND "+prefix+"person_code IN (SELECT person_code FROM family_binding WHERE user_id=?)";}
    @GetMapping({"/api/v1/events","/api/v1/events/page","/api/v1/events/latest"}) Object events(HttpServletRequest r,@RequestParam(defaultValue="1")int page,@RequestParam(defaultValue="20")int size,@RequestParam Map<String,String> filters){
        var u=auth.user(r);Api.require(page>=1&&size>=1&&size<=100,"分页范围无效");var args=new ArrayList<Object>();String where=" WHERE 1=1"+scope(u,args,"");
        for(var key:Map.of("eventType","event_type","cameraCode","camera_code","personCode","person_code","status","status").entrySet())if(filters.containsKey(key.getKey())&&!filters.get(key.getKey()).isBlank()){where+=" AND "+key.getValue()+"=?";args.add(filters.get(key.getKey()));}
        for(var key:Map.of("startTime",">=","endTime","<=").entrySet())if(filters.containsKey(key.getKey())&&!filters.get(key.getKey()).isBlank()){where+=" AND event_time "+key.getValue()+" ?";args.add(Timestamp.valueOf(LocalDateTime.parse(filters.get(key.getKey()))));}
        long total=s.db.queryForObject("SELECT COUNT(*) FROM event"+where,Long.class,args.toArray());args.add(size);args.add((page-1)*size);
        var rows=s.rows("SELECT id FROM event"+where+" ORDER BY event_time DESC,id DESC LIMIT ? OFFSET ?",args.toArray()).stream().map(v->eventRow(Long.parseLong(v.get("id").toString()))).toList();
        return r.getRequestURI().endsWith("/latest")?Api.ok(rows):Api.ok(Map.of("records",rows,"total",total,"current",page,"size",size,"pages",(total+size-1)/size));
    }
    @GetMapping("/api/v1/events/{id}") Object event(HttpServletRequest r,@PathVariable long id){var row=eventRow(id);auth.event(auth.user(r),row);return Api.ok(row);}
    @GetMapping("/api/v1/events/{id}/records") Object records(HttpServletRequest r,@PathVariable long id){auth.event(auth.user(r),eventRow(id));return Api.ok(s.rows("SELECT r.*,u.real_name AS operator_name FROM event_handle_record r LEFT JOIN sys_user u ON r.operator_id=u.id WHERE event_id=? ORDER BY r.id",id));}
    @PutMapping("/api/v1/events/{id}/status") Object status(HttpServletRequest r,@PathVariable long id,@RequestBody Map<String,Object>b){var u=auth.user(r);auth.staff(u);String next=Api.text(b,"status",20);Api.require(Set.of("PROCESSING","DONE").contains(next),"状态只能改为PROCESSING或DONE");tx.executeWithoutResult(t->{var old=s.one("SELECT * FROM event WHERE id=? FOR UPDATE",id);String previous=old.get("status").toString();if(previous.equals(next))return;if(previous.equals("DONE"))throw new Api(409,"已完成事件不能退回");s.db.update("UPDATE event SET status=? WHERE id=?",next,id);s.db.update("INSERT INTO event_handle_record(event_id,operator_id,old_status,new_status,remark) VALUES(?,?,?,?,?)",id,u.id(),previous,next,Api.optional(b,"remark",500));s.log(u,"EVENT_STATUS",id+":"+previous+"->"+next);afterCommit(()->{cache.invalidate();socket.send("EVENT_STATUS_UPDATED",eventRow(id));});});return Api.ok(eventRow(id));}
    @GetMapping("/api/v1/events/{id}/snapshot") ResponseEntity<?> image(HttpServletRequest r,@PathVariable long id){var row=s.one("SELECT * FROM event WHERE id=?",id);auth.event(auth.user(r),row);return ResponseEntity.ok().contentType(MediaType.IMAGE_JPEG).cacheControl(CacheControl.noStore()).body(new FileSystemResource(media.path(row.get("imagePath"))));}
    @DeleteMapping("/api/v1/events/{id}") Object deleteEvent(HttpServletRequest r,@PathVariable long id){var u=auth.user(r);auth.admin(u);var event=s.one("SELECT * FROM event WHERE id=?",id);Object imagePath=event.get("imagePath");var videoPaths=s.rows("SELECT file_path FROM event_video WHERE event_id=?",id);tx.executeWithoutResult(t->{s.db.update("DELETE FROM notification_job WHERE event_id=?",id);s.db.update("DELETE FROM event_handle_record WHERE event_id=?",id);s.db.update("DELETE FROM event_video WHERE event_id=?",id);s.db.update("DELETE FROM event WHERE id=?",id);s.log(u,"DELETE_EVENT",Long.toString(id));afterCommit(()->{cache.invalidate();var payload=new HashMap<String,Object>();payload.put("id",Long.toString(id));payload.put("personCode",event.get("personCode"));socket.send("EVENT_DELETED",payload);});});if(imagePath!=null)media.delete(imagePath.toString());for(var v:videoPaths){Object p=v.get("filePath");if(p!=null)media.delete(p.toString());}return Api.ok(null);}
    @GetMapping({"/api/v1/events/statistics","/api/v1/statistics/event-count"}) Object statistics(HttpServletRequest r){var user=auth.user(r);boolean shared=!user.role().equals("FAMILY");long revision=cache.revision.get();if(shared){var cached=cache.get(revision);if(cached!=null)return Api.ok(cached);}var args=new ArrayList<Object>();String where=" WHERE 1=1"+scope(auth.user(r),args,"");var result=new LinkedHashMap<String,Object>();result.put("total",s.db.queryForObject("SELECT COUNT(*) FROM event"+where,Long.class,args.toArray()));for(String status:List.of("PENDING","PROCESSING","DONE")){var a=new ArrayList<>(args);a.add(status);result.put(status.toLowerCase(),s.db.queryForObject("SELECT COUNT(*) FROM event"+where+" AND status=?",Long.class,a.toArray()));}args.add(Timestamp.valueOf(LocalDate.now(ZoneId.of("Asia/Shanghai")).atStartOfDay()));result.put("today",s.db.queryForObject("SELECT COUNT(*) FROM event"+where+" AND event_time>=?",Long.class,args.toArray()));if(shared)cache.put(revision,result);return Api.ok(result);}
    @GetMapping("/api/v1/statistics/type-count") Object typeCount(HttpServletRequest r){var a=new ArrayList<Object>();return Api.ok(s.rows("SELECT event_type,COUNT(*) AS count FROM event WHERE 1=1"+scope(auth.user(r),a,"")+" GROUP BY event_type",a.toArray()));}
    @GetMapping("/api/v1/statistics/event-trend") Object trend(HttpServletRequest r){var a=new ArrayList<Object>();String w=scope(auth.user(r),a,"");a.add(Timestamp.valueOf(LocalDate.now(ZoneId.of("Asia/Shanghai")).minusDays(6).atStartOfDay()));return Api.ok(s.rows("SELECT CAST(event_time AS DATE) AS day,COUNT(*) AS count FROM event WHERE 1=1"+w+" AND event_time>=? GROUP BY CAST(event_time AS DATE) ORDER BY day",a.toArray()));}
    @GetMapping("/api/v1/persons") Object persons(HttpServletRequest r){var a=new ArrayList<Object>();return Api.ok(s.rows("SELECT id,person_code,name,person_type,note,enabled,face_state,face_error,version FROM person WHERE enabled=TRUE"+scope(auth.user(r),a,"")+" ORDER BY id",a.toArray()));}
    @PostMapping("/api/v1/persons") Object createPerson(HttpServletRequest r,@RequestBody Map<String,Object>b){var u=auth.user(r);auth.admin(u);String type=Api.text(b,"personType",20);Api.require(Set.of("ELDER","WORKER","FAMILY").contains(type),"人员类别无效");long id=s.insert("INSERT INTO person(person_code,name,person_type,note) VALUES(?,?,?,?)",Api.text(b,"personCode",64),Api.text(b,"name",100),type,Api.optional(b,"note",500));s.log(u,"CREATE_PERSON",Long.toString(id));return Api.ok(Map.of("id",Long.toString(id)));}
    @PutMapping("/api/v1/persons/{code}") Object updatePerson(HttpServletRequest r,@PathVariable String code,@RequestBody Map<String,Object>b){var u=auth.user(r);auth.admin(u);s.db.update("UPDATE person SET name=?,note=?,version=version+1,face_state=CASE WHEN face_path IS NULL THEN 'NONE' ELSE 'PENDING' END WHERE person_code=?",Api.text(b,"name",100),Api.optional(b,"note",500),code);s.log(u,"UPDATE_PERSON",code);return Api.ok(null);}
    @DeleteMapping("/api/v1/persons/{code}") Object deletePerson(HttpServletRequest r,@PathVariable String code){var u=auth.user(r);auth.admin(u);s.db.update("UPDATE person SET enabled=FALSE,version=version+1,face_state='PENDING' WHERE person_code=?",code);s.log(u,"DELETE_PERSON",code);return Api.ok(null);}
    @PostMapping("/api/v1/persons/{code}/face") Object uploadFace(HttpServletRequest r,@PathVariable String code,@RequestPart MultipartFile file)throws Exception{auth.admin(auth.user(r));s.one("SELECT id FROM person WHERE person_code=? AND enabled=TRUE",code);String name=media.save(media.image(file),".jpg");Api.require(name!=null,"照片不能为空");try{s.db.update("UPDATE person SET face_path=?,face_state='PENDING',face_error=NULL,version=version+1 WHERE person_code=?",name,code);}catch(Exception e){media.delete(name);throw e;}return Api.ok(Map.of("state","PENDING"));}
    @GetMapping("/api/v1/persons/{code}/face") ResponseEntity<?> personFace(HttpServletRequest r,@PathVariable String code){var u=auth.user(r);Map<String,Object> row;if(u.role().equals("FAMILY"))row=s.one("SELECT p.face_path FROM person p JOIN family_binding f ON f.person_code=p.person_code WHERE p.person_code=? AND p.enabled=TRUE AND f.user_id=?",code,u.id());else row=s.one("SELECT face_path FROM person WHERE person_code=? AND enabled=TRUE",code);Object path=row.get("facePath");if(path==null)throw new Api(404,"尚未上传人脸照片");return ResponseEntity.ok().contentType(MediaType.IMAGE_JPEG).cacheControl(CacheControl.noStore()).body(new FileSystemResource(media.path(path)));}
    @GetMapping("/api/v1/cameras") Object cameras(HttpServletRequest r){auth.staff(auth.user(r));return Api.ok(s.rows("SELECT id,camera_code,camera_name,location,capture_source,node_code,enabled,CASE WHEN last_seen IS NULL OR last_seen < ? THEN 'OFFLINE' ELSE status END AS status,last_seen,config_json,version,applied_version,error_message FROM camera ORDER BY id",Timestamp.valueOf(LocalDateTime.now().minusSeconds(15))));}
    @PostMapping("/api/v1/cameras") Object cameraCreate(HttpServletRequest r,@RequestBody Map<String,Object>b){var u=auth.user(r);auth.admin(u);long id=s.insert("INSERT INTO camera(camera_code,camera_name,location,capture_source,node_code,config_json) VALUES(?,?,?,?,?,?)",Api.text(b,"cameraCode",64),Api.text(b,"cameraName",100),Api.text(b,"location",255),Api.text(b,"captureSource",500),auth.nodeCode,"{}");s.log(u,"CREATE_CAMERA",Long.toString(id));return Api.ok(Map.of("id",Long.toString(id)));}
    @PutMapping("/api/v1/cameras/{code}") Object cameraUpdate(HttpServletRequest r,@PathVariable String code,@RequestBody Map<String,Object>b){var u=auth.user(r);auth.admin(u);var config=b.getOrDefault("config",Map.of());Api.require(config instanceof Map,"config必须是对象");Validation.cameraConfig((Map<?,?>)config);s.db.update("UPDATE camera SET camera_name=?,location=?,capture_source=?,enabled=?,config_json=?,version=version+1 WHERE camera_code=?",Api.text(b,"cameraName",100),Api.text(b,"location",255),Api.text(b,"captureSource",500),Boolean.TRUE.equals(b.get("enabled")),s.encode(config),code);s.log(u,"UPDATE_CAMERA",code);return Api.ok(null);}
    @GetMapping("/api/v1/danger-zones") Object zones(HttpServletRequest r){auth.staff(auth.user(r));return Api.ok(s.rows("SELECT * FROM danger_zone ORDER BY id"));}
    @PostMapping("/api/v1/danger-zones") Object zoneCreate(HttpServletRequest r,@RequestBody Map<String,Object>b){var u=auth.user(r);auth.admin(u);String camera=Api.text(b,"cameraCode",64);s.one("SELECT id FROM camera WHERE camera_code=?",camera);String points=points(b);long id=s.insert("INSERT INTO danger_zone(zone_code,camera_code,zone_name,points_json,enter_seconds,exit_seconds) VALUES(?,?,?,?,?,?)",Api.text(b,"zoneCode",64),camera,Api.text(b,"zoneName",100),points,Validation.seconds(b.getOrDefault("enterSeconds",1),"enterSeconds"),Validation.seconds(b.getOrDefault("exitSeconds",2),"exitSeconds"));s.log(u,"CREATE_ZONE",Long.toString(id));return Api.ok(Map.of("id",Long.toString(id)));}
    String points(Map<String,Object>b){Api.require(b.get("points") instanceof List,"points必须是数组");var points=(List<?>)b.get("points");Api.require(points.size()>=3&&points.size()<=32,"多边形需要3到32个顶点");for(Object p:points){Api.require(p instanceof List&&((List<?>)p).size()==2,"顶点需要x,y");for(Object v:(List<?>)p)Api.require(v instanceof Number&&Double.isFinite(((Number)v).doubleValue())&&((Number)v).doubleValue()>=0&&((Number)v).doubleValue()<=1,"坐标必须归一化到0到1");}Validation.polygon(points);return s.encode(points);}
    @PutMapping("/api/v1/danger-zones/{code}") Object zoneUpdate(HttpServletRequest r,@PathVariable String code,@RequestBody Map<String,Object>b){var u=auth.user(r);auth.admin(u);String p=points(b);s.db.update("UPDATE danger_zone SET points_json=?,zone_name=?,enabled=?,enter_seconds=?,exit_seconds=?,version=version+1 WHERE zone_code=?",p,Api.text(b,"zoneName",100),Boolean.TRUE.equals(b.get("enabled")),Validation.seconds(b.getOrDefault("enterSeconds",1),"enterSeconds"),Validation.seconds(b.getOrDefault("exitSeconds",2),"exitSeconds"),code);s.log(u,"UPDATE_ZONE",code);return Api.ok(null);}
    @DeleteMapping("/api/v1/danger-zones/{code}") Object zoneDelete(HttpServletRequest r,@PathVariable String code){auth.admin(auth.user(r));s.db.update("UPDATE danger_zone SET enabled=FALSE,version=version+1 WHERE zone_code=?",code);return Api.ok(null);}
    @GetMapping("/api/v1/ai/config") Object config(HttpServletRequest r){auth.ai(r);return Api.ok(Map.of("cameras",s.rows("SELECT * FROM camera WHERE node_code=?",auth.nodeCode),"zones",s.rows("SELECT z.* FROM danger_zone z JOIN camera c ON z.camera_code=c.camera_code WHERE c.node_code=?",auth.nodeCode),"persons",s.rows("SELECT person_code,name,person_type,enabled,version,face_state,CASE WHEN face_path IS NULL THEN FALSE ELSE TRUE END AS has_face FROM person")));}
    @GetMapping("/api/v1/ai/persons/{code}/face") ResponseEntity<?> aiFace(HttpServletRequest r,@PathVariable String code){auth.ai(r);return ResponseEntity.ok().contentType(MediaType.IMAGE_JPEG).cacheControl(CacheControl.noStore()).body(new FileSystemResource(media.path(s.one("SELECT face_path FROM person WHERE person_code=? AND enabled=TRUE",code).get("facePath"))));}
    @PostMapping("/api/v1/ai/ack") Object ack(HttpServletRequest r,@RequestBody Map<String,Object>b){auth.ai(r);String kind=Api.text(b,"kind",20),code=Api.text(b,"code",64);long version=Long.parseLong(Api.text(b,"version",30));if(kind.equals("person")){String state=Api.text(b,"state",20);Api.require(Set.of("ACTIVE","FAILED","REMOVED","NONE").contains(state),"无效状态");if(s.db.update("UPDATE person SET face_state=?,face_error=? WHERE person_code=? AND version=?",state,Api.optional(b,"error",255),code,version)!=1)throw new Api(409,"人员配置已变更，请重新同步");}else if(kind.equals("camera")){auth.cameraForAI(code);if(s.db.update("UPDATE camera SET applied_version=? WHERE camera_code=? AND version=?",version,code,version)!=1)throw new Api(409,"摄像头配置已变更，请重新同步");}else if(kind.equals("zone")){var z=s.one("SELECT camera_code FROM danger_zone WHERE zone_code=?",code);auth.cameraForAI(z.get("cameraCode").toString());if(s.db.update("UPDATE danger_zone SET applied_version=? WHERE zone_code=? AND version=?",version,code,version)!=1)throw new Api(409,"区域配置已变更，请重新同步");}else throw new Api(400,"未知配置种类");return Api.ok(null);}
    @PostMapping("/api/v1/ai/heartbeat") Object heartbeat(HttpServletRequest r,@RequestBody Map<String,Object>b){auth.ai(r);String code=Api.text(b,"cameraCode",64);auth.cameraForAI(code);String status=Api.text(b,"status",20);Api.require(Set.of("ONLINE","OFFLINE","ERROR","DISABLED").contains(status),"状态无效");s.db.update("UPDATE camera SET status=?,last_seen=CURRENT_TIMESTAMP,error_message=? WHERE camera_code=?",status,Api.optional(b,"error",255),code);return Api.ok(null);}
    
    // ==========================================
    // 电子围栏管理接口
    // ==========================================
    
    @GetMapping("/api/v1/geofences") Object geofences(HttpServletRequest r){
        auth.staff(auth.user(r));
        return Api.ok(s.rows("SELECT * FROM geofence ORDER BY id"));
    }
    
    @PostMapping("/api/v1/geofences") Object geofenceCreate(HttpServletRequest r,@RequestBody Map<String,Object>b){
        var u=auth.user(r);
        auth.admin(u);
        String points=geofencePoints(b);
        long id=s.insert("INSERT INTO geofence(fence_code,fence_name,points_json,enabled) VALUES(?,?,?,?)",
            Api.text(b,"fenceCode",64),
            Api.text(b,"fenceName",100),
            points,
            Boolean.TRUE.equals(b.getOrDefault("enabled",Boolean.TRUE)));
        s.log(u,"CREATE_GEOFENCE",Long.toString(id));
        return Api.ok(Map.of("id",Long.toString(id)));
    }
    
    String geofencePoints(Map<String,Object>b){
        Api.require(b.get("points") instanceof List,"points必须是经纬度数组");
        var points=(List<?>)b.get("points");
        Api.require(points.size()>=3&&points.size()<=32,"多边形需要3到32个顶点");
        for(Object p:points){
            Api.require(p instanceof List&&((List<?>)p).size()==2,"顶点需要lng,lat");
            var coord=(List<?>)p;
            double lng=((Number)coord.get(0)).doubleValue();
            double lat=((Number)coord.get(1)).doubleValue();
            Api.require(Double.isFinite(lng)&&lng>=73&&lng<=135,"经度范围无效");
            Api.require(Double.isFinite(lat)&&lat>=3&&lat<=54,"纬度范围无效");
        }
        Validation.polygon(points);
        return s.encode(points);
    }
    
    @PutMapping("/api/v1/geofences/{code}") Object geofenceUpdate(HttpServletRequest r,@PathVariable String code,@RequestBody Map<String,Object>b){
        var u=auth.user(r);
        auth.admin(u);
        String p=geofencePoints(b);
        s.db.update("UPDATE geofence SET points_json=?,fence_name=?,enabled=?,version=version+1 WHERE fence_code=?",
            p,Api.text(b,"fenceName",100),Boolean.TRUE.equals(b.get("enabled")),code);
        s.log(u,"UPDATE_GEOFENCE",code);
        return Api.ok(null);
    }
    
    @DeleteMapping("/api/v1/geofences/{code}") Object geofenceDelete(HttpServletRequest r,@PathVariable String code){
        auth.admin(auth.user(r));
        s.db.update("UPDATE geofence SET enabled=FALSE,version=version+1 WHERE fence_code=?",code);
        return Api.ok(null);
    }
    
    // ==========================================
    // 人员设备绑定接口
    // ==========================================
    
    @GetMapping("/api/v1/person-device-bindings") Object deviceBindings(HttpServletRequest r){
        auth.admin(auth.user(r));
        return Api.ok(s.rows("SELECT * FROM person_device_binding ORDER BY id"));
    }
    
    @PostMapping("/api/v1/person-device-bindings") Object bindDevice(HttpServletRequest r,@RequestBody Map<String,Object>b){
        var u=auth.user(r);
        auth.admin(u);
        String personCode=Api.text(b,"personCode",64);
        String deviceId=Api.text(b,"deviceId",128);
        Api.require("ELDER".equals(s.one("SELECT person_type FROM person WHERE person_code=? AND enabled=TRUE",personCode).get("personType")),"只能绑定老人");
        try{
            s.db.update("INSERT INTO person_device_binding(person_code,device_id) VALUES(?,?)",personCode,deviceId);
        }catch(DuplicateKeyException ignored){}
        s.log(u,"BIND_DEVICE",personCode+":"+deviceId);
        return Api.ok(null);
    }
    
    @DeleteMapping("/api/v1/person-device-bindings") Object unbindDevice(HttpServletRequest r,@RequestParam String personCode){
        var u=auth.user(r);
        auth.admin(u);
        s.db.update("DELETE FROM person_device_binding WHERE person_code=?",personCode);
        s.log(u,"UNBIND_DEVICE",personCode);
        return Api.ok(null);
    }
    
    // ==========================================
    // 北斗位置数据接收接口
    // ==========================================
    
    @PostMapping("/api/v1/location/update") Object locationUpdate(HttpServletRequest r,@RequestBody Map<String,Object>b){
        auth.ai(r);
        String deviceId=Api.text(b,"deviceId",128);
        var binding=s.rows("SELECT person_code FROM person_device_binding WHERE device_id=? AND enabled=TRUE",deviceId);
        Api.require(!binding.isEmpty(),"设备未绑定老人");
        String personCode=binding.get(0).get("personCode").toString();
        
        double lng=((Number)b.get("longitude")).doubleValue();
        double lat=((Number)b.get("latitude")).doubleValue();
        Api.require(Double.isFinite(lng)&&lng>=73&&lng<=135,"经度无效");
        Api.require(Double.isFinite(lat)&&lat>=3&&lat<=54,"纬度无效");
        
        Double accuracy=b.get("accuracy")!=null?((Number)b.get("accuracy")).doubleValue():null;
        Double altitude=b.get("altitude")!=null?((Number)b.get("altitude")).doubleValue():null;
        Double speed=b.get("speed")!=null?((Number)b.get("speed")).doubleValue():null;
        Double direction=b.get("direction")!=null?((Number)b.get("direction")).doubleValue():null;
        
        var time=LocalDateTime.parse(Api.text(b,"sampleTime",40));
        String pointNo=Api.text(b,"pointNo",64);
        
        // 判断是否在围栏内
        var fences=s.rows("SELECT fence_code,points_json FROM geofence WHERE enabled=TRUE");
        Boolean insideFence=null;
        String fenceCode=null;
        if(!fences.isEmpty()){
            var fence=fences.get(0);
            fenceCode=fence.get("fenceCode").toString();
            var pointsJson=fence.get("pointsJson").toString();
            insideFence=isPointInPolygon(lng,lat,pointsJson);
        }
        
        // 保存位置历史
        s.db.update("INSERT INTO location_history(point_no,person_code,device_id,longitude,latitude,accuracy,altitude,speed,direction,sample_time,inside_fence,fence_code) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            pointNo,personCode,deviceId,lng,lat,accuracy,altitude,speed,direction,Timestamp.valueOf(time),insideFence,fenceCode);
        
        // 保存轨迹点（兼容现有表结构）
        try{
            s.db.update("INSERT INTO track_point(point_no,camera_code,track_id,person_code,sample_time,x,y,longitude,latitude,accuracy,source) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                pointNo,"GPS",deviceId,personCode,Timestamp.valueOf(time),lng,lat,lng,lat,accuracy,"GPS");
        }catch(Exception e){
            // track_point可能还没有新字段，忽略错误
        }
        
        // ⭐ 方案一：异步转发数据给 AI 服务进行实时告警分析
        forwardToAiServiceAsync(b);
        
        return Api.ok(Map.of("insideFence",insideFence,"fenceCode",fenceCode));
    }
    
    /**
     * 异步转发位置数据到 AI 服务 (127.0.0.1:5002)
     * 采用 fire-and-forget 策略，不影响主接口的响应速度
     */
    private void forwardToAiServiceAsync(Map<String,Object> locationData){
        CompletableFuture.runAsync(() -> {
            try{
                String aiUrl = System.getenv().getOrDefault("AI_SERVICE_URL", "http://127.0.0.1:5002") + "/api/v1/location/update";
                String apiKey = System.getenv().getOrDefault("AI_SERVICE_KEY", "");
                
                if(apiKey.isEmpty()) {
                    org.slf4j.LoggerFactory.getLogger(PlatformController.class).warn("AI_SERVICE_KEY is empty, skipping forward to AI service");
                    return;
                }

                String jsonBody = new com.fasterxml.jackson.databind.ObjectMapper().writeValueAsString(locationData);
                
                HttpClient client = HttpClient.newHttpClient();
                HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(aiUrl))
                    .header("Content-Type", "application/json")
                    .header("X-AI-Key", apiKey)
                    .POST(HttpRequest.BodyPublishers.ofString(jsonBody))
                    .timeout(java.time.Duration.ofSeconds(3))
                    .build();
                    
                // 发送请求但不等待结果，仅记录错误
                client.sendAsync(request, HttpResponse.BodyHandlers.discarding())
                    .exceptionally(ex -> {
                        org.slf4j.LoggerFactory.getLogger(PlatformController.class).error("Failed to forward location to AI service: {}", ex.getMessage());
                        return null;
                    });
                    
            }catch(Exception e){
                org.slf4j.LoggerFactory.getLogger(PlatformController.class).error("Error preparing AI forward task: {}", e.getMessage());
            }
        });
    }
    
    boolean isPointInPolygon(double lng,double lat,String pointsJson){
        try{
            var points=s.array(pointsJson);
            int n=points.size();
            boolean inside=false;
            for(int i=0,j=n-1;i<n;j=i++){
                var pointI=(List<Number>)points.get(i);
                var pointJ=(List<Number>)points.get(j);
                double xi=pointI.get(0).doubleValue();
                double yi=pointI.get(1).doubleValue();
                double xj=pointJ.get(0).doubleValue();
                double yj=pointJ.get(1).doubleValue();
                
                boolean intersect=((yi>lat)!=(yj>lat))&&(lng<(xj-xi)*(lat-yi)/(yj-yi)+xi);
                if(intersect)inside=!inside;
            }
            return inside;
        }catch(Exception e){
            return false;
        }
    }
    
    // ==========================================
    // 轨迹查询接口
    // ==========================================
    
    @GetMapping("/api/v1/tracks/{personCode}") Object tracks(HttpServletRequest r,@PathVariable String personCode,@RequestParam(required=false)String startTime,@RequestParam(required=false)String endTime){
        var u=auth.user(r);
        if(u.role().equals("FAMILY")){
            s.one("SELECT 1 FROM family_binding WHERE user_id=? AND person_code=?",u.id(),personCode);
        }
        
        var args=new ArrayList<Object>();
        args.add(personCode);
        String where=" WHERE person_code=?";
        
        if(startTime!=null&&!startTime.isBlank()){
            where+=" AND sample_time>=?";
            args.add(Timestamp.valueOf(LocalDateTime.parse(startTime)));
        }
        if(endTime!=null&&!endTime.isBlank()){
            where+=" AND sample_time<=?";
            args.add(Timestamp.valueOf(LocalDateTime.parse(endTime)));
        }
        
        var rows=s.rows("SELECT * FROM location_history"+where+" ORDER BY sample_time DESC LIMIT 1000",args.toArray());
        return Api.ok(rows);
    }
    
    @GetMapping("/api/v1/location/last-known/{personCode}") Object lastKnownLocation(HttpServletRequest r,@PathVariable String personCode){
        var u=auth.user(r);
        if(u.role().equals("FAMILY")){
            s.one("SELECT 1 FROM family_binding WHERE user_id=? AND person_code=?",u.id(),personCode);
        }
        
        var row=s.rows("SELECT * FROM location_history WHERE person_code=? ORDER BY sample_time DESC LIMIT 1",personCode);
        if(row.isEmpty())throw new Api(404,"无位置数据");
        return Api.ok(row.get(0));
    }
}
