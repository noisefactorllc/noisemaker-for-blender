#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))), ivec2(0), textureSize((s),0)-ivec2(1)), 0))
void main() {
    vec2 uv = gl_FragCoord.xy / resolution;
    
    vec4 inputColor = nmTex(inputTex, uv);
    vec4 trailColor = nmTex(trailTex, uv);
    
    // Additive blend: trail + scaled input
    // inputIntensity 0 = black, 100 = trail + full input
    float t = inputIntensity / 100.0;
    float matteAlpha = matteOpacity;
    
    // Trail presence based on max RGB channel
    float trailPresence = max(max(trailColor.r, trailColor.g), trailColor.b);
    
    // Background contribution is scaled by matte opacity (premultiplied)
    // Trail contribution is NOT affected by matte opacity
    vec3 rgb = trailColor.rgb + inputColor.rgb * t * matteAlpha;
    
    // Alpha: where trail exists, full opacity; elsewhere, matte opacity
    float alpha = max(trailPresence, matteAlpha);
    
    fragColor = vec4(rgb, alpha);
}
