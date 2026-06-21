float luminance(vec4 c) {
    return dot(c.rgb, vec3(0.2126, 0.7152, 0.0722));
}

void main() {
    vec2 globalCoord = gl_FragCoord.xy + tileOffset;
    vec2 st = globalCoord / fullResolution;

    float r = luminance(texture(rTex, gl_FragCoord.xy / vec2(textureSize(rTex, 0)))) * rLevel / 100.0;
    float g = luminance(texture(gTex, gl_FragCoord.xy / vec2(textureSize(gTex, 0)))) * gLevel / 100.0;
    float b = luminance(texture(bTex, gl_FragCoord.xy / vec2(textureSize(bTex, 0)))) * bLevel / 100.0;

    fragColor = vec4(r, g, b, 1.0);
}
