package com.eldercare.platform;
import org.junit.jupiter.api.Test;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

class ValidationTest {
    @Test void rejectCrossedOrDegenerateZones(){
        assertThrows(Api.class,()->Validation.polygon(List.of(List.of(0,0),List.of(1,1),List.of(0,1),List.of(1,0))));
        assertThrows(Api.class,()->Validation.polygon(List.of(List.of(0,0),List.of(.5,.5),List.of(1,1))));
        assertDoesNotThrow(()->Validation.polygon(List.of(List.of(0,0),List.of(1,0),List.of(1,1),List.of(0,1))));
    }
    @Test void configRejectsTyposAndUnsafeDurations(){
        assertThrows(Api.class,()->Validation.cameraConfig(Map.of("sadSecond",30)));
        assertThrows(Api.class,()->Validation.cameraConfig(Map.of("sadSeconds",0)));
        assertThrows(Api.class,()->Validation.cameraConfig(Map.of("fallEnabled","false")));
        assertDoesNotThrow(()->Validation.cameraConfig(Map.of("sadSeconds",30,"fallEnabled",false)));
    }
}
