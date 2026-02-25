FROM eclipse-temurin:17-jre-alpine
WORKDIR /app
COPY target/api-gateway-service.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java","-jar","app.jar"]
