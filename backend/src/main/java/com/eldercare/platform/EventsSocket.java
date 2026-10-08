package com.eldercare.platform;

import org.springframework.context.annotation.Configuration;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.socket.*;
import org.springframework.web.socket.handler.TextWebSocketHandler;
import org.springframework.web.socket.config.annotation.*;
import org.springframework.web.socket.server.HandshakeInterceptor;
import org.springframework.web.socket.handler.ConcurrentWebSocketSessionDecorator;
import org.springframework.http.server.*;
import org.springframework.http.HttpStatus;
import org.springframework.web.util.UriComponentsBuilder;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

@Component
public class EventsSocket extends TextWebSocketHandler implements HandshakeInterceptor {
    final Auth auth; final Store store;
    final ConcurrentHashMap<String,WebSocketSession> sessions=new ConcurrentHashMap<>();
    EventsSocket(Auth auth,Store store){this.auth=auth;this.store=store;}
    public boolean beforeHandshake(ServerHttpRequest request,ServerHttpResponse response,WebSocketHandler handler,Map<String,Object> attrs){
        var ticket=UriComponentsBuilder.fromUri(request.getURI()).build().getQueryParams().getFirst("ticket");
        var user=auth.consume(ticket);if(user==null){response.setStatusCode(HttpStatus.UNAUTHORIZED);return false;}attrs.put("user",user);return true;
    }
    public void afterHandshake(ServerHttpRequest q,ServerHttpResponse r,WebSocketHandler h,Exception e){}
    public void afterConnectionEstablished(WebSocketSession s){sessions.put(s.getId(),new ConcurrentWebSocketSessionDecorator(s,5000,65536));}
    public void afterConnectionClosed(WebSocketSession s,CloseStatus c){sessions.remove(s.getId());}
    public void handleTransportError(WebSocketSession s,Throwable e)throws Exception{sessions.remove(s.getId());s.close();}
    @Scheduled(fixedDelay=5000) public void expire(){for(var s:sessions.values())try{if(!auth.valid((Auth.User)s.getAttributes().get("user"))){s.close(CloseStatus.POLICY_VIOLATION);sessions.remove(s.getId());}}catch(Exception e){try{s.close();}catch(Exception ignored){}sessions.remove(s.getId());}}
    void send(String type,Map<String,Object> event){for(var s:sessions.values())try{var u=(Auth.User)s.getAttributes().get("user");if(auth.valid(u)&&auth.canPerson(u,event.get("personCode")))s.sendMessage(new TextMessage(store.encode(Map.of("messageType",type,"data",event))));}catch(Exception e){try{s.close();}catch(Exception ignored){}sessions.remove(s.getId());}}
}

@Configuration
@EnableWebSocket
class SocketConfiguration implements WebSocketConfigurer {
    final EventsSocket socket;final String[] origins;
    SocketConfiguration(EventsSocket socket,@Value("${app.origins}")String origins){this.socket=socket;this.origins=origins.split(",");}
    public void registerWebSocketHandlers(WebSocketHandlerRegistry r){r.addHandler(socket,"/ws/events").addInterceptors(socket).setAllowedOrigins(origins);}
}
