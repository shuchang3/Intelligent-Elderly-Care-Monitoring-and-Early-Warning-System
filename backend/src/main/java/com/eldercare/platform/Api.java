package com.eldercare.platform;

import java.util.*;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.dao.DataAccessException;

public class Api extends RuntimeException {
    final int status;
    public Api(int status, String message) { super(message); this.status = status; }
    static Map<String,Object> ok(Object data) {
        var body = new LinkedHashMap<String,Object>(); body.put("code",200);body.put("message","success");body.put("data",data); return body;
    }
    static String text(Map<String,?> body, String key, int max) {
        var v=body.get(key); String s=v==null?"":v.toString().trim();
        if(s.isEmpty()||s.length()>max) throw new Api(400,key+"不能为空且长度不能超过"+max); return s;
    }
    static String optional(Map<String,?> body,String key,int max) {
        var v=body.get(key); if(v==null||v.toString().isBlank())return null;
        return text(body,key,max);
    }
    static void require(boolean condition,String message) { if(!condition)throw new Api(400,message); }
}

@RestControllerAdvice
class Errors {
    @ExceptionHandler(Api.class) ResponseEntity<?> api(Api e){return error(e.status,e.getMessage());}
    @ExceptionHandler({IllegalArgumentException.class,MissingServletRequestParameterException.class,MethodArgumentTypeMismatchException.class,HttpMessageNotReadableException.class})
    ResponseEntity<?> bad(Exception e){return error(400,"请求参数无效");}
    @ExceptionHandler(org.springframework.dao.DuplicateKeyException.class) ResponseEntity<?> conflict(Exception e){return error(409,"业务编号已存在");}
    @ExceptionHandler({org.springframework.web.multipart.support.MissingServletRequestPartException.class,java.time.format.DateTimeParseException.class}) ResponseEntity<?> missing(Exception e){return error(400,"缺少上传文件或时间格式无效");}
    @ExceptionHandler(org.springframework.web.multipart.MaxUploadSizeExceededException.class) ResponseEntity<?> tooLarge(Exception e){return error(413,"上传文件超过大小限制");}
    @ExceptionHandler(DataAccessException.class) ResponseEntity<?> database(Exception e){org.slf4j.LoggerFactory.getLogger(Errors.class).error("Database request failed",e);return error(503,"数据库暂不可用，请检查后台日志");}
    @ExceptionHandler(Exception.class) ResponseEntity<?> unknown(Exception e){org.slf4j.LoggerFactory.getLogger(Errors.class).error("Request failed: {}",e.getClass().getSimpleName());return error(500,"服务处理失败");}
    private ResponseEntity<?> error(int code,String message){return ResponseEntity.status(code).body(Map.of("code",code,"message",message));}
}
