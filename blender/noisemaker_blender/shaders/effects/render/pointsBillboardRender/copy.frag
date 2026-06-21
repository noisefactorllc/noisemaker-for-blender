// Copy Pass - Blit source to destination (for ping-pong correction)

void main() {
    vec2 uv = gl_FragCoord.xy / resolution;
    fragColor = texture(sourceTex, uv);
}
