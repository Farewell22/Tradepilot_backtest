# 构建阶段
FROM node:20-alpine AS builder

WORKDIR /app

# 使用国内 npm 镜像加速
COPY package*.json ./
RUN npm ci --registry=https://registry.npmmirror.com

COPY . .
RUN npm run build

# 运行阶段 - 使用 Nginx 托管静态文件
FROM nginx:alpine

# 复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 复制 Nginx 配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
