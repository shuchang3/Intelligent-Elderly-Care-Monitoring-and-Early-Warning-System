package com.eldercare.platform;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableScheduling
public class Application {
    public static void main(String[] args) {
        var context = SpringApplication.run(Application.class, args);
        if (Boolean.parseBoolean(context.getEnvironment().getProperty("app.initialize", "false"))) context.close();
    }
}
