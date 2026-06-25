#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))), ivec2(0), textureSize((s),0)-ivec2(1)), 0))
void main() {
    vec2 uv = gl_FragCoord.xy / resolution;

    vec4 inputColor = nmTex(inputTex, uv);
    vec4 trailColor = nmTex(trailTex, uv);

    float t = inputIntensity / 100.0;
    vec4 scaledInput = inputColor * t;

    vec3 outRGB;
    float outAlpha;

    if (blendMode == 1) {
        // Alpha mode: trail stores premultiplied values (rgb = actual_color * alpha).
        // Use premultiplied OVER operator then convert to straight for output.
        outAlpha = trailColor.a + scaledInput.a * (1.0 - trailColor.a);
        vec3 outRGB_pre = trailColor.rgb + scaledInput.rgb * scaledInput.a * (1.0 - trailColor.a);
        outRGB = outAlpha > 0.0 ? outRGB_pre / outAlpha : vec3(0.0);
    } else {
        // Additive mode: clamp trail to [0,1] then screen-blend with input (avoids overflow).
        vec3 trail = clamp(trailColor.rgb, 0.0, 1.0);
        float trailPresence = max(max(trail.r, trail.g), trail.b);
        outRGB = trail + scaledInput.rgb * (1.0 - trail);
        outAlpha = max(trailPresence, scaledInput.a);
    }

    fragColor = clamp(vec4(outRGB, outAlpha), 0.0, 1.0);
}
