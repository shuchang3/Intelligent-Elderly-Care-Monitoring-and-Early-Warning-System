package com.eldercare.platform;

import org.springframework.stereotype.Component;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.multipart.MultipartFile;
import java.nio.file.*;
import java.io.*;
import java.security.MessageDigest;
import java.util.*;
import javax.imageio.ImageIO;

@Component
class Media {
    final Path root;
    Media(@Value("${app.storage}")String path)throws IOException{root=Path.of(path).toAbsolutePath().normalize();Files.createDirectories(root);}
    byte[] image(MultipartFile file)throws IOException{
        if(file==null||file.isEmpty())return null;
        Api.require(file.getSize()<=10*1024*1024,"图片不能超过10MB");
        try(var in=ImageIO.createImageInputStream(file.getInputStream())){
            var readers=ImageIO.getImageReaders(in);Api.require(readers.hasNext(),"不支持的图片格式");var reader=readers.next();
            try{reader.setInput(in);Api.require((long)reader.getWidth(0)*reader.getHeight(0)<=20_000_000,"图片尺寸过大");var img=reader.read(0);var rgb=new java.awt.image.BufferedImage(img.getWidth(),img.getHeight(),java.awt.image.BufferedImage.TYPE_INT_RGB);var g=rgb.createGraphics();g.drawImage(img,0,0,null);g.dispose();var out=new ByteArrayOutputStream();Api.require(ImageIO.write(rgb,"jpg",out),"图片编码失败");return out.toByteArray();}finally{reader.dispose();}
        }
    }
    String save(byte[] bytes,String extension)throws IOException{if(bytes==null)return null;String name=UUID.randomUUID()+extension;Path temp=Files.createTempFile(root,"writing-",".tmp");try{Files.write(temp,bytes);Files.move(temp,root.resolve(name),StandardCopyOption.REPLACE_EXISTING);}finally{Files.deleteIfExists(temp);}return name;}
    Path path(Object name){if(name==null)throw new Api(404,"媒体尚未生成");Path p=root.resolve(name.toString()).normalize();if(!p.startsWith(root)||!Files.isRegularFile(p))throw new Api(404,"媒体不存在");return p;}
    void delete(String name){if(name==null)return;try{Path p=root.resolve(name).normalize();if(p.startsWith(root))Files.deleteIfExists(p);}catch(IOException ignored){}}
    static String hash(byte[] bytes){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));}catch(Exception e){throw new IllegalStateException(e);}}
}
