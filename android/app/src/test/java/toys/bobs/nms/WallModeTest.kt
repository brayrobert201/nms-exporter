package toys.bobs.nms

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class WallModeTest {
    @Test fun cyclesTheDefaultOrder() {
        val d = WallMode.DEFAULT
        assertEquals("gathering", WallMode.next("idle", d))
        assertEquals("crafting", WallMode.next("gathering", d))
        assertEquals("mission", WallMode.next("crafting", d))
        assertEquals("idle", WallMode.next("mission", d))
        assertEquals("idle", WallMode.next("bogus", d))
        assertEquals("idle", WallMode.next(null, d))
        assertEquals("gathering", WallMode.next("idle", emptyList()))
    }

    @Test fun followsTheServersList() {
        val s = WallMode.parse("""{"activity":"crafting","activities":["idle","crafting","flying"]}""")
        assertEquals(listOf("idle", "crafting", "flying"), s.activities)
        assertEquals("flying", WallMode.next(s.activity, s.activities))
        assertFalse(s.idle)
    }

    @Test fun fallsBackWithoutAList() {
        val s = WallMode.parse("""{"activity":"idle","crafting":false}""")
        assertEquals(WallMode.DEFAULT, s.activities)
        assertTrue(s.idle)
        assertNull(s.error)
    }

    @Test fun readsAnError() {
        val s = WallMode.parse("""{"error":"unknown activity"}""")
        assertNull(s.activity)
        assertEquals("unknown activity", s.error)
    }

    @Test fun labelsAndBody() {
        assertEquals("Gathering", WallMode.label("gathering"))
        assertEquals("Deep space", WallMode.label("deep_space"))
        assertEquals("""{"activity":"mission"}""", WallMode.body("mission"))
    }
}
