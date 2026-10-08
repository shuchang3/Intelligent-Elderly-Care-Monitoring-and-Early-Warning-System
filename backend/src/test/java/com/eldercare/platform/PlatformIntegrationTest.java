package com.eldercare.platform;

import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import java.net.*;
import java.net.http.*;
import java.util.*;
import java.util.concurrent.*;
import java.time.Duration;
import java.nio.charset.StandardCharsets;
import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.RANDOM_PORT,properties={"spring.datasource.url=jdbc:h2:mem:platform;MODE=MySQL;DB_CLOSE_DELAY=-1;DATABASE_TO_LOWER=TRUE","spring.datasource.username=sa","spring.datasource.password=","app.jwt-secret=integration-secret-at-least-32-characters-long","app.ai-key=integration-ai-key-at-least-32-characters-long","app.storage=./target/test-media"})
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class PlatformIntegrationTest {
    @Autowired Store store;
    @Autowired Auth auth;
    @LocalServerPort int port;
    HttpClient client=HttpClient.newHttpClient();
    String password="Local-test-password-2026";
    @BeforeAll void initialize(){new Store(store.db,true,password,password).run(null);}
    HttpResponse<String> call(String method,String path,String token,Object body)throws Exception{
        var b=HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+path)).timeout(Duration.ofSeconds(10));
        if(token!=null)b.header("Authorization","Bearer "+token);
        b.header("Content-Type","application/json");return client.send(b.method(method,body==null?HttpRequest.BodyPublishers.noBody():HttpRequest.BodyPublishers.ofString(store.encode(body))).build(),HttpResponse.BodyHandlers.ofString());
    }
    Map<String,Object> data(HttpResponse<String> r){assertEquals(200,r.statusCode(),r.body());return (Map<String,Object>)store.object(r.body()).get("data");}
    String login(String name)throws Exception{return data(call("POST","/api/v1/auth/login",null,Map.of("username",name,"password",password))).get("token").toString();}
    HttpResponse<String> report(String no,String description)throws Exception{
        String boundary="test-boundary";var fields=new LinkedHashMap<String,String>();fields.put("eventNo",no);fields.put("eventType","FALL");fields.put("cameraCode","CAM001");fields.put("eventTime","2026-09-01T08:00:00");fields.put("description",description);StringBuilder body=new StringBuilder();for(var e:fields.entrySet())body.append("--"+boundary+"\r\nContent-Disposition: form-data; name=\""+e.getKey()+"\"\r\n\r\n"+e.getValue()+"\r\n");body.append("--"+boundary+"--\r\n");return client.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+"/api/v1/ai/events")).header("Content-Type","multipart/form-data; boundary="+boundary).header("X-AI-Key","integration-ai-key-at-least-32-characters-long").POST(HttpRequest.BodyPublishers.ofString(body.toString())).build(),HttpResponse.BodyHandlers.ofString());
    }
    @Test void healthAndAuthentication()throws Exception{assertEquals(200,call("GET","/health",null,null).statusCode());assertEquals(401,call("GET","/api/v1/events/page",null,null).statusCode());assertEquals("ADMIN",data(call("GET","/api/v1/auth/me",login("admin"),null)).get("role"));assertEquals(403,call("GET","/api/v1/users",login("staff01"),null).statusCode());}
    @Test void idempotencyAndConflict()throws Exception{String no=UUID.randomUUID().toString();var one=data(report(no,"safe synthetic test"));var two=data(report(no,"safe synthetic test"));assertEquals(one.get("id"),two.get("id"));assertEquals(409,report(no,"different payload").statusCode());assertEquals(1,store.db.queryForObject("SELECT count(*) FROM event WHERE event_no=?",Integer.class,no));}
    @Test void concurrentRetryCreatesOneRow()throws Exception{String no=UUID.randomUUID().toString();try(var executor=Executors.newFixedThreadPool(4)){var futures=new ArrayList<Future<HttpResponse<String>>>();for(int i=0;i<4;i++)futures.add(executor.submit(()->report(no,"concurrent")));for(var f:futures)assertEquals(200,f.get().statusCode());}assertEquals(1,store.db.queryForObject("SELECT count(*) FROM event WHERE event_no=?",Integer.class,no));}
    @Test void donePersistsWithOneRecord()throws Exception{String token=login("staff01"),id=data(report(UUID.randomUUID().toString(),"state test")).get("id").toString();assertEquals(200,call("PUT","/api/v1/events/"+id+"/status",token,Map.of("status","DONE")).statusCode());assertEquals("DONE",data(call("GET","/api/v1/events/"+id,token,null)).get("status"));assertEquals(409,call("PUT","/api/v1/events/"+id+"/status",token,Map.of("status","PROCESSING")).statusCode());assertEquals(1,store.db.queryForObject("SELECT count(*) FROM event_handle_record WHERE event_id=?",Integer.class,id));}
    @Test void revokedUserCannotKeepOldToken()throws Exception{String user="staff_"+UUID.randomUUID().toString().substring(0,8);store.db.update("INSERT INTO sys_user(username,password,real_name,role) VALUES(?,?,?,?)",user,auth.encoder.encode(password),user,"STAFF");String token=login(user);store.db.update("UPDATE sys_user SET status='DISABLED' WHERE username=?",user);assertEquals(401,call("GET","/api/v1/auth/me",token,null).statusCode());}
    @Test void familyCannotReadUnboundEventOrMedia()throws Exception{String user="family_"+UUID.randomUUID().toString().substring(0,8);store.db.update("INSERT INTO sys_user(username,password,real_name,role) VALUES(?,?,?,?)",user,auth.encoder.encode(password),user,"FAMILY");String token=login(user),id=data(report(UUID.randomUUID().toString(),"privacy test")).get("id").toString();assertEquals(403,call("GET","/api/v1/events/"+id,token,null).statusCode());assertEquals(403,call("GET","/api/v1/events/"+id+"/snapshot",token,null).statusCode());assertEquals(403,call("GET","/api/v1/cameras",token,null).statusCode());assertEquals(0,((List<?>)data(call("GET","/api/v1/events/page",token,null)).get("records")).size());}
    @Test void websocketTicketSingleUseAndEventDelivery()throws Exception{String token=login("admin");String ticket=data(call("POST","/api/v1/auth/ws-ticket",token,Map.of())).get("ticket").toString();var received=new CompletableFuture<String>();var buffer=new StringBuilder();WebSocket ws=client.newWebSocketBuilder().buildAsync(URI.create("ws://127.0.0.1:"+port+"/ws/events?ticket="+ticket),new WebSocket.Listener(){public CompletionStage<?> onText(WebSocket w,CharSequence text,boolean last){buffer.append(text);if(last)received.complete(buffer.toString());w.request(1);return null;}}).get(5,TimeUnit.SECONDS);report(UUID.randomUUID().toString(),"websocket");assertEquals("EVENT_CREATED",store.object(received.get(5,TimeUnit.SECONDS)).get("messageType"));assertThrows(ExecutionException.class,()->client.newWebSocketBuilder().buildAsync(URI.create("ws://127.0.0.1:"+port+"/ws/events?ticket="+ticket),new WebSocket.Listener(){}).get());ws.sendClose(1000,"done").get();}
}
