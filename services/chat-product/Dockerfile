# build stage
FROM maven:3.9.5-eclipse-temurin-17 AS build
WORKDIR /workspace
COPY pom.xml ./
RUN mvn -B -f pom.xml dependency:go-offline

COPY src src
RUN mvn -B -DskipTests package

# run stage
FROM eclipse-temurin:17-jdk
RUN groupadd -r appuser && useradd -r -g appuser appuser
WORKDIR /app
COPY --from=build /workspace/target/*.jar app.jar
RUN chown -R appuser:appuser /app
USER appuser
EXPOSE 8081
ENTRYPOINT ["java","-jar","/app/app.jar"]
