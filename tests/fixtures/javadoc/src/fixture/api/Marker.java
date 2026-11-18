package fixture.api;

import java.lang.annotation.Documented;
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Marks a type that a mod may extend.
 */
@Documented
@Retention(RetentionPolicy.RUNTIME)
@Target(ElementType.TYPE)
public @interface Marker {

    /**
     * Why the type may be extended.
     *
     * @return the reason
     */
    String value();

    /**
     * Release that allowed it.
     *
     * @return the release number
     */
    int since() default 1;
}
