package com.eldercare.platform;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.RedisConnectionFailureException;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
class OptionalCacheTest {
    @Test void unavailableRedisDoesNotBreakBusinessQueries(){
        var redis=mock(StringRedisTemplate.class);
        when(redis.opsForValue()).thenThrow(new RedisConnectionFailureException("offline"));
        var cache=new OptionalCache(redis,new Store(null,false,"",""),true);
        assertNull(cache.get(0));assertDoesNotThrow(()->cache.put(0,Map.of("total",4)));
        cache.invalidate();assertEquals(1,cache.revision.get());assertEquals("DEGRADED",cache.health());
    }
    @Test void disabledCacheDoesNotOpenAnyConnection(){
        var redis=mock(StringRedisTemplate.class);var cache=new OptionalCache(redis,null,false);
        assertNull(cache.get(0));cache.put(0,Map.of());assertEquals("DISABLED",cache.health());verifyNoInteractions(redis);
    }
}
