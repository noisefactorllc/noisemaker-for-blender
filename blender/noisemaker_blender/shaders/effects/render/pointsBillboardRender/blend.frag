#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))), ivec2(0), textureSize((s),0)-ivec2(1)), 0))
void main() {
    vec2 uv = gl_FragCoord.xy / resolution;
    
    vec4 inputColor = nmTex(inputTex, uv);
    vec4 trailColor = nmTex(trailTex, uv);
    
    // Blend: trail over scaled input using alpha
    // inputIntensity 0 = trail only, 100 = trail over full input
    float t = inputIntensity / 100.0;
    vec4 scaledInput = inputColor * t;
    
    // Alpha compositing: trail over input
    float outAlpha = trailColor.a + scaledInput.a * (1.0 - trailColor.a);
    vec3 outRGB = outAlpha > 0.0 
        ? (trailColor.rgb * trailColor.a + scaledInput.rgb * scaledInput.a * (1.0 - trailColor.a)) / outAlpha
        : vec3(0.0);
    
    fragColor = vec4(outRGB, outAlpha);
}
