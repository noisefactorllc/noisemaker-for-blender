#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))), ivec2(0), textureSize((s),0)-ivec2(1)), 0))
/*
 * Emboss convolution effect
 * Creates a raised relief appearance
 */

void main() {
    vec2 globalCoord = gl_FragCoord.xy + tileOffset;
    ivec2 texSize = textureSize(inputTex, 0);
    vec2 resolution = vec2(texSize);
    vec2 uv = globalCoord / fullResolution;
    vec2 texelSize = 1.0 / resolution;
    
    vec4 origColor = nmTex(inputTex, gl_FragCoord.xy / vec2(textureSize(inputTex, 0)));
    
    // Emboss nm_kernel
    // -2 -1  0
    // -1  1  1
    //  0  1  2
    float nm_kernel[9];
    nm_kernel[0] = -2.0; nm_kernel[1] = -1.0; nm_kernel[2] = 0.0;
    nm_kernel[3] = -1.0; nm_kernel[4] = 1.0;  nm_kernel[5] = 1.0;
    nm_kernel[6] = 0.0;  nm_kernel[7] = 1.0;  nm_kernel[8] = 2.0;
    
    vec2 offsets[9];
    offsets[0] = vec2(-texelSize.x, -texelSize.y);
    offsets[1] = vec2(0.0, -texelSize.y);
    offsets[2] = vec2(texelSize.x, -texelSize.y);
    offsets[3] = vec2(-texelSize.x, 0.0);
    offsets[4] = vec2(0.0, 0.0);
    offsets[5] = vec2(texelSize.x, 0.0);
    offsets[6] = vec2(-texelSize.x, texelSize.y);
    offsets[7] = vec2(0.0, texelSize.y);
    offsets[8] = vec2(texelSize.x, texelSize.y);
    
    vec3 conv = vec3(0.0);
    
    for (int i = 0; i < 9; i++) {
        vec3 texSample = nmTex(inputTex, ((uv + offsets[i] * amount * renderScale) * fullResolution - tileOffset) / vec2(textureSize(inputTex, 0))).rgb;
        conv += texSample * nm_kernel[i];
    }
    
    fragColor = vec4(clamp(conv, 0.0, 1.0), origColor.a);
}
