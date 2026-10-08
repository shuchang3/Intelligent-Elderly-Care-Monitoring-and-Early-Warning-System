package com.eldercare.platform;

import java.time.Duration;
import java.util.*;
import java.util.concurrent.atomic.AtomicLong;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.data.redis.core.StringRedisTemplate;

/** Optional single-instance dashboard cache. Authorization is checked before every read.
 * Family data is deliberately never cached. Revision keys prevent an old in-flight
 * query from re-populating the current cache after an event transaction commits. */
@Component
class OptionalCache {
    final StringRedisTemplate redis;final Store store;final boolean enabled;
    final AtomicLong revision=new AtomicLong();
    final String prefix="elder-care:"+UUID.randomUUID()+":";
    OptionalCache(StringRedisTemplate redis,Store store,@Value("${app.redis-enabled:false}") boolean enabled){this.redis=redis;this.store=store;this.enabled=enabled;}
    Map<String,Object> get(long version){
        if(!enabled)return null;
        try{String raw=redis.opsForValue().get(prefix+version);return raw==null?null:store.object(raw);}catch(Exception unavailable){return null;}
    }
    void put(long version,Map<String,Object> value){
        if(!enabled)return;
        try{redis.opsForValue().set(prefix+version,store.encode(value),Duration.ofSeconds(10));}catch(Exception unavailable){/* MySQL response remains authoritative. */}
    }
    void invalidate(){revision.incrementAndGet();}
    String health(){
        if(!enabled)return "DISABLED";
        try(var connection=Objects.requireNonNull(redis.getConnectionFactory()).getConnection()){return "PONG".equals(connection.ping())?"UP":"DEGRADED";}catch(Exception e){return "DEGRADED";}
    }
}
