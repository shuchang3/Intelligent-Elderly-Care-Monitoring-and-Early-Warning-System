package com.eldercare.platform;

import jakarta.servlet.*;
import jakarta.servlet.http.*;
import java.io.IOException;
import java.util.Map;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/** Authenticate before record lookups, including media, so missing IDs do not
 * become an unauthenticated record-existence oracle. Controller checks still
 * enforce roles and person scope. */
@Component
class ApiAuthenticationFilter extends OncePerRequestFilter {
    final Auth auth;final Store store;
    ApiAuthenticationFilter(Auth auth,Store store){this.auth=auth;this.store=store;}
    protected void doFilterInternal(HttpServletRequest req,HttpServletResponse res,FilterChain chain)throws ServletException,IOException{
        String path=req.getRequestURI();
        try{
            if(path.startsWith("/api/v1/ai/")||path.equals("/api/v1/location/update"))auth.ai(req);
            else if(path.startsWith("/api/v1/")&&!path.equals("/api/v1/auth/login"))auth.user(req);
        }catch(Api e){error(res,e.status,e.getMessage());return;}
        catch(org.springframework.dao.DataAccessException e){error(res,503,"数据库暂不可用");return;}
        chain.doFilter(req,res);
    }
    void error(HttpServletResponse res,int code,String message)throws IOException{
        res.setStatus(code);res.setContentType("application/json");res.setCharacterEncoding("UTF-8");res.getWriter().write(store.encode(Map.of("code",code,"message",message)));
    }
}
