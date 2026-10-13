package com.example.lostandfound

import com.example.lostandfound.util.Validators
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ValidatorsTest {
    @Test
    fun tenDigitIndianMobileGetsCountryCode() {
        assertEquals("+919876543210", Validators.normalizePhone("98765 43210"))
        assertEquals("+919876543210", Validators.normalizePhone(" 9876543210 "))
    }

    @Test
    fun internationalNumbersKeepTheirCode() {
        assertEquals("+919876543210", Validators.normalizePhone("+91 98765-43210"))
        assertEquals("+447911123456", Validators.normalizePhone("+44 (7911) 123456"))
    }

    @Test
    fun implausibleNumbersAreRejected() {
        assertNull(Validators.normalizePhone(""))
        assertNull(Validators.normalizePhone("12345"))
        assertNull(Validators.normalizePhone("5876543210")) // Indian mobiles start with 6-9
        assertNull(Validators.normalizePhone("98765abc10"))
        assertNull(Validators.normalizePhone("+91 98765 43210; drop table"))
        assertNull(Validators.normalizePhone("919876543210")) // 12 digits without "+" is ambiguous
    }
}
