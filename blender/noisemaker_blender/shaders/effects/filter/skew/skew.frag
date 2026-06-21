#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))), ivec2(0), textureSize((s),0)-ivec2(1)), 0))
/*
 * Skew and rotate transform
 */

const float PI = 3.14159265359;

void main() {
    ivec2 texSize = textureSize(inputTex, 0);
    vec2 resolution = vec2(texSize);
    
    // Compute global pixel coordinate and global UV
    vec2 globalPixel = gl_FragCoord.xy + tileOffset;
    vec2 globalUV = globalPixel / fullResolution;
    
    // Use full image aspect ratio for consistent transformation across tiles
    float aspect = fullResolution.x / fullResolution.y;

    // Apply transformation in global UV space
    vec2 st = globalUV;
    st -= 0.5;
    st.x *= aspect;

    float angle = rotation * PI / 180.0;
    float c = cos(angle);
    float s = sin(angle);
    st = mat2(c, -s, s, c) * st;

    // Bound skew to prevent displacement beyond overlap region
    float maxSkew = 512.0 / fullResolution.y;
    float effectiveSkewAmt = clamp(skewAmt, -maxSkew, maxSkew);
    st.x += st.y * -effectiveSkewAmt;

    st.x /= aspect;
    st += 0.5;

    // Convert from global UV to tile-local UV for sampling
    vec2 localUV = (st * fullResolution - tileOffset) / resolution;

    // Apply wrap mode in local UV space for seamless tile rendering
    int wrapMode = int(wrap);
    if (wrapMode == 0) {
        // clamp
        localUV = clamp(localUV, 0.0, 1.0);
    } else if (wrapMode == 1) {
        // mirror
        localUV = abs(mod(localUV + 1.0, 2.0) - 1.0);
    } else {
        // repeat
        localUV = fract(localUV);
    }

    fragColor = nmTex(inputTex, localUV);
}
